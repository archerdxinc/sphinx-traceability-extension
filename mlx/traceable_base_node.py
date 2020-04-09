""" Module for the base class for all Traceability node classes. """
import re
from abc import abstractmethod, ABC

from docutils import nodes
from sphinx.errors import NoUri
from sphinx.builders.latex import LaTeXBuilder

from mlx.traceability_exception import report_warning
from mlx.traceable_item import TraceableItem

# External relationship: starts with ext_
# An external relationship is a relationship where the item to link to is not in the
# traceability system, but on an external tool. Translating the link to a clickable
# hyperlink is done through the config traceability_external_relationship_to_url.
REGEXP_EXTERNAL_RELATIONSHIP = re.compile('^ext_.*')
EXTERNAL_LINK_FIELDNAME = 'field'


class TraceableBaseNode(nodes.General, nodes.Element, ABC):
    """ Base class for all Traceability node classes. """

    def create_top_node(self, title, app=None):
        ''' Creates the top node for the Element node. An admonition object with given title is created and returns.

        Args:
            title (str): Title or item ID of the top node
            app (sphinx.application.Sphinx): Optional application object, needed when item ID is given to create link

        Returns:
            Top level replacement node to which other nodes can be appended
        '''
        top_node = nodes.container()
        admon_node = nodes.admonition()
        admon_node['classes'].append('item')
        title_node = nodes.title()
        if app:
            showcaptions = not self['nocaptions']
            title_node += self.make_internal_item_ref(app, title, showcaptions).children[0]
        else:
            title_node += nodes.Text(title)
        admon_node += title_node
        top_node += admon_node
        return top_node

    @abstractmethod
    def perform_replacement(self, app, collection):
        """ Performs the traceability node replacement.

        Args:
            app: Sphinx application object to use.
            collection (TraceableCollection): Collection for which to generate the nodes.
        """

    def make_internal_item_ref(self, app, item_id, show_caption=True):
        """
        Creates a reference node for an item, embedded in a
        paragraph. Reference text adds also a caption if it exists.
        """
        env = app.builder.env
        item_info = env.traceability_collection.get_item(item_id)
        notification_item = None

        p_node = nodes.paragraph()

        # Only create link when target item (or notification item) exists, warn otherwise (in html and terminal)
        if item_info.is_placeholder():
            notification_item_id = app.config.traceability_notifications.get('undefined-reference')
            notification_item = app.env.traceability_collection.get_item(notification_item_id)
            if not notification_item:
                self.has_warned_about_undefined(item_info)
                txt = nodes.Text('%s not defined, broken link' % item_id)
                p_node.append(txt)
                return p_node

        caption, caption_on_hover = self._get_caption_info(item_info, show_caption=show_caption)

        newnode = nodes.reference('', '')
        innernode = nodes.emphasis(item_id + caption, item_id + caption)
        try:
            if not notification_item:
                newnode['refuri'] = app.builder.get_relative_uri(self['document'], item_info.docname)
                newnode['refuri'] += '#' + item_id
                newnode['refdocname'] = item_info.docname
            else:
                newnode['refuri'] = app.builder.get_relative_uri(self['document'], notification_item.docname)
                newnode['refuri'] += '#' + notification_item_id
                newnode['refdocname'] = notification_item.docname
        except NoUri:
            # ignore if no URI can be determined, e.g. for LaTeX output :(
            pass

        # change text color if item_id matches a regex in traceability_hyperlink_colors
        colors = self._find_colors_for_class(app.config.traceability_hyperlink_colors, item_id)
        if colors:
            class_name = app.config.traceability_class_names[colors]
            newnode['classes'].append(class_name)
        if caption_on_hover and not isinstance(app.builder, LaTeXBuilder):
            innernode['classes'].append('has_hidden_caption')
            innernode.append(caption_on_hover)  # set to hidden in traceability.js
        newnode.append(innernode)
        p_node += newnode

        return p_node

    @staticmethod
    def make_external_item_ref(app, target_text, relationship):
        '''Generates a reference to an external item.'''
        if relationship not in app.config.traceability_external_relationship_to_url:
            return
        p_node = nodes.paragraph()
        link = nodes.reference()
        txt = nodes.Text(target_text)
        tgt_strs = target_text.split(':')  # syntax = field1:field2:field3:...
        url = app.config.traceability_external_relationship_to_url[relationship]
        cnt = 0
        for tgt_str in tgt_strs:
            cnt += 1
            url = url.replace(EXTERNAL_LINK_FIELDNAME + str(cnt), tgt_str)
        link['refuri'] = url
        link.append(txt)
        targetid = nodes.make_id(target_text)
        target = nodes.target('', '', ids=[targetid])
        p_node += target
        p_node += link
        return p_node

    def is_item_top_level(self, env, item_id):
        '''
        Checks if item with given item ID is a top level item.

        True, if the item is a top level item:

        - given relation does not exist for given item,
        - or given relation exists, but targets don't match the 'top' regexp.

        False, otherwise.
        '''
        item = env.traceability_collection.get_item(item_id)
        for relation in self['top_relation_filter']:
            tgts = item.iter_targets(relation)
            for tgt in tgts:
                if re.match(self['top'], tgt):
                    return False
        return True

    def make_attribute_ref(self, app, attr_id, value=''):
        """
        Creates a reference node for an attribute, embedded in a paragraph.
        """
        p_node = nodes.paragraph()

        if value:
            value = ': ' + value

        if attr_id in TraceableItem.defined_attributes:
            attr_info = TraceableItem.defined_attributes[attr_id]
            attr_name = attr_info.get_name()
            if attr_info.docname:
                newnode = nodes.reference('', '')
                innernode = nodes.emphasis(attr_name + value, attr_name + value)
                newnode['refdocname'] = attr_info.docname
                try:
                    newnode['refuri'] = app.builder.get_relative_uri(self['document'], attr_info.docname)
                    newnode['refuri'] += '#' + attr_info.get_name()
                except NoUri:
                    # ignore if no URI can be determined, e.g. for LaTeX output :(
                    pass
                newnode.append(innernode)
            else:
                newnode = nodes.Text('{attr}{value}'.format(attr=attr_info.get_name(), value=value))
        else:
            newnode = nodes.Text('{attr}{value}'.format(attr=attr_id, value=value))
        p_node += newnode

        return p_node

    @staticmethod
    def _find_colors_for_class(hyperlink_colors, item_id):
        """
        Returns CSS class identifier to change a node's text color if the item ID matches a regexp in hyperlink_colors.
        The regexp of the first item in the ordered dictionary has the highest priority.

        Args:
            hyperlink_colors (OrderedDict): Ordered dict with regex strings as keys and list/tuple of strings as values.
            item_id (str): A traceability item ID.

        Returns:
            (tuple) Tuple of color strings that should be used to color the given item ID or None if no match was found.
        """
        for regex, colors in hyperlink_colors.items():
            colors = tuple(colors)
            if re.search(regex, item_id):
                return tuple(colors)
        return None

    @staticmethod
    def _get_caption_info(item_info, show_caption=True):
        """ Gets either the caption or the caption to show on hover, depending on the item's configuration.

        Args:
            item_info (TraceableItem): TraceableItem object.
            show_caption (bool): True if the caption should always be shown, False to only show caption on hover.

        Returns:
            str: Caption to append to the item's ID, or empty string when item has no caption or it is configured to be
                shown on hover
            nodes.inline/None: Inline node containing the item's caption, or None if caption should always be shown.
        """
        caption = ''
        caption_on_hover = None
        if item_info and item_info.caption:
            if show_caption:
                caption = ' : {}'.format(item_info.caption)
            else:
                caption_on_hover = nodes.inline('', item_info.caption)
                caption_on_hover['classes'].append('popup_caption')
        return caption, caption_on_hover

    def has_warned_about_undefined(self, item_info):
        """
        Reports a warning if the given node is a placeholder node. Returns True if this is the case, False otherwise.

        Args:
            item_info (TraceableItem): TraceableItem object.
        """
        if item_info.is_placeholder():
            report_warning("Traceability: cannot link to '%s', item is not defined" % item_info.get_id(),
                           self['document'], self['line'])
            return True
        return False
