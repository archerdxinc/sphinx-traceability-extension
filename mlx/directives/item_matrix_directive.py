import re
from collections import namedtuple

from docutils import nodes
from docutils.parsers.rst import directives

from mlx.traceability_exception import report_warning
from mlx.traceable_base_directive import TraceableBaseDirective
from mlx.traceable_base_node import TraceableBaseNode


def group(argument):
    """Conversion function for the "group" option."""
    return directives.choice(argument, ('top', 'bottom'))


class ItemMatrix(TraceableBaseNode):
    '''Matrix for cross referencing documentation items'''

    def perform_replacement(self, app, collection):
        """
        Creates table with related items, printing their target references. Only source and target items matching
        respective regexp shall be included.

        Args:
            app: Sphinx application object to use.
            collection (TraceableCollection): Collection for which to generate the nodes.
        """

        # The 'target' attribute might be empty, in which case a catch-all is implied. In this case, we set
        # number_of_columns to 2 (one source, one target). In other cases, it's the number of target settings + 1 source
        # column
        number_of_columns = max(2, len(self['target']) + 1)
        Rows = namedtuple('Rows', "sorted covered uncovered")
        source_ids = collection.get_items(self['source'], self['filter-attributes'])
        targets_with_ids = []
        for target_regex in self['target']:
            targets_with_ids.append(collection.get_items(target_regex))
        top_node = self.create_top_node(self['title'])
        table = nodes.table()
        if self.get('classes'):
            table.get('classes').extend(self.get('classes'))
        tgroup = nodes.tgroup()

        # Column and heading setup
        tgroup += [nodes.colspec(colwidth=5) for _ in range(number_of_columns)]
        headings = [nodes.entry('', nodes.paragraph('', title))
                    for title in [self['sourcetitle'], *self['targettitle']]]
        tgroup += nodes.thead('', nodes.row('', *headings))

        # The table body
        tbody = nodes.tbody()
        tgroup += tbody
        table += tgroup

        # External relationships are treated a bit special in item-matrices:
        # - External references are only shown if explicitly requested in the "type" configuration
        # - No target filtering is done on external references

        relationships = self['type']
        if not relationships:
            # if no explicit relationships were given, we consider all of them (except for external ones)
            relationships = [rel for rel in collection.iter_relations() if not self.is_relation_external(rel)]
            external_relationships = []
        else:
            external_relationships = [rel for rel in relationships if self.is_relation_external(rel)]

        ext_relations_to_target_map = {}
        for relation in external_relationships:
            ext_targets_to_item_ids = collection.get_external_targets(self['source'], relation)
            ext_relations_to_target_map[relation] = ext_targets_to_item_ids

        count_covered = 0
        rows = Rows([], [], [])
        for source_id in source_ids:
            source_item = collection.get_item(source_id)
            covered = False
            left = nodes.entry()
            left += self.make_internal_item_ref(app, source_id)
            rights = [nodes.entry('') for _ in range(number_of_columns - 1)]
            for ext_relationship in external_relationships:
                for target_id in source_item.iter_targets(ext_relationship):
                    ext_item_ref = self.make_external_item_ref(app, target_id, ext_relationship)
                    for right in rights:
                        right += ext_item_ref
                    covered = True
            for idx, target_ids in enumerate(targets_with_ids):
                for target_id in target_ids:
                    if collection.are_related(source_id, relationships, target_id):
                        rights[idx] += self.make_internal_item_ref(app, target_id)
                        covered = True
            self._store_row(rows, left, rights, covered)

        for ext_rel, ext_targets_to_item_ids in ext_relations_to_target_map.items():
            for ext_source, item_ids in ext_targets_to_item_ids.items():
                covered = False
                left = nodes.entry()
                left += self.make_external_item_ref(app, ext_source, ext_rel)
                rights = [nodes.entry('') for _ in range(number_of_columns - 1)]
                for idx, target_regex in enumerate(self['target']):
                    for target_id in item_ids:
                        if re.match(target_regex, target_id):
                            rights[idx] += self.make_internal_item_ref(app, target_id)
                            covered = True

                self._store_row(rows, left, rights, covered)


        if not self['group']:
            tbody += rows.sorted
        elif self['group'] == 'top':
            tbody += rows.uncovered
            tbody += rows.covered
        elif self['group'] == 'bottom':
            tbody += rows.covered
            tbody += rows.uncovered

        count_total = len(rows.sorted)
        count_covered = len(rows.covered)
        try:
            percentage = int(100 * count_covered / count_total)
        except ZeroDivisionError:
            percentage = 0
        disp = 'Statistics: {cover} out of {total} covered: {pct}%'.format(cover=count_covered,
                                                                           total=count_total,
                                                                           pct=percentage)
        if self['stats']:
            p_node = nodes.paragraph()
            txt = nodes.Text(disp)
            p_node += txt
            top_node += p_node

        top_node += table
        self.replace_self(top_node)

    @staticmethod
    def _store_row(rows, left, rights, covered):
        row = nodes.row()
        row += left
        for right in rights:  # TODO refactor
            row += right

        rows.sorted.append(row)
        if covered:
            rows.covered.append(row)
        else:
            rows.uncovered.append(row)


class ItemMatrixDirective(TraceableBaseDirective):
    """
    Directive to generate a matrix of item cross-references, based on
    a given set of relationship types.

    Syntax::

      .. item-matrix:: title
         :target: regexp
         :source: regexp
         :<<attribute>>: regexp
         :targettitle: Target column header
         :sourcetitle: Source column header
         :type: <<relationship>> ...
         :group: top | bottom
         :stats:
         :nocaptions:
    """
    # Optional argument: title (whitespace allowed)
    optional_arguments = 1
    # Options
    option_spec = {
        'class': directives.class_option,
        'target': directives.unchanged,
        'source': directives.unchanged,
        'targettitle': directives.unchanged,
        'sourcetitle': directives.unchanged,
        'type': directives.unchanged,  # a string with relationship types separated by space
        'group': group,
        'stats': directives.flag,
        'nocaptions': directives.flag,
    }
    # Content disallowed
    has_content = False

    def run(self):
        env = self.state.document.settings.env
        app = env.app

        item_matrix_node = ItemMatrix('')
        item_matrix_node['document'] = env.docname
        item_matrix_node['line'] = self.lineno

        if self.options.get('class'):
            item_matrix_node.get('classes').extend(self.options.get('class'))

        self.process_title(item_matrix_node, 'Traceability matrix of items')

        self.add_found_attributes(item_matrix_node)

        self.process_options(
            item_matrix_node,
            {
                'target':      {'default': ['']},
                'source':      {'default': ''},
                'targettitle': {'default': ['Target'], 'delimiter': ','},
                'sourcetitle': {'default': 'Source'},
                'type':        {'default': []},
            },
        )

        # Process ``group`` option, given as a string that is either top or bottom or empty ().
        item_matrix_node['group'] = self.options.get('group', '')

        number_of_targets = len(item_matrix_node['target'])
        number_of_targettitles = len(item_matrix_node['targettitle'])
        if number_of_targets > 1 and number_of_targets != number_of_targettitles:
            report_warning("Item-matrix directive should have the same number of 'target' attributes as 'target-title' "
                           "attributes. Got target: {targets} and targettitle: {titles}"
                           .format(targets=item_matrix_node['target'], titles=item_matrix_node['targettitle']),
                           env.docname, self.lineno)

        self.check_relationships(item_matrix_node['type'], env)

        self.check_option_presence(item_matrix_node, 'stats')

        self.check_caption_flags(item_matrix_node, app.config.traceability_matrix_no_captions)

        return [item_matrix_node]
