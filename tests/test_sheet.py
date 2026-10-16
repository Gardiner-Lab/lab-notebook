"""The server's table arithmetic (app/sheet.py) gives what the page's (sheet.js) shows: the same cases as tests/js/sheet.test.js."""

from app import sheet


def table(columns, rows, scale=None):
    return {'columns': [{'name': c, 'kind': c} if isinstance(c, str) else c for c in columns],
            'rows': [{'cells': cells} for cells in rows], 'scale': scale}


def shown(t):
    return [[c['display'] for c in row] for row in sheet.compute(t)]


def test_numbers_formulas_ranges_and_functions():
    assert shown(table(['number', 'number'], [['2', '=A1*3'], ['0.5', '=SUM(A1:A2)+ROUND(1.236,2)']])) == \
        [['2', '6'], ['0.5', '3.74']]


def test_column_formulas_and_scaling():
    mix = table([{'kind': 'text'}, {'kind': 'number'}, {'kind': 'formula', 'formula': '=B*N'}],
                [['Buffer', '2', ''], ['Water', '=20-SUM(B1:B1)', '']], {'label': 'Reactions', 'value': 3, 'base': 1})
    assert shown(mix) == [['Buffer', '2', '6'], ['Water', '18', '54']]
    assert shown(table(['scaled'], [['1.5']], {'value': 4, 'base': 2})) == [['3']]


def test_moclo_volumes_wait_for_concentrations():
    moclo = table([{'kind': 'text'}, {'kind': 'number'}, {'kind': 'number'}, {'kind': 'fill'},
                   {'kind': 'formula', 'formula': '=B*C*660/1000000'}, {'kind': 'formula', 'formula': '=E/D'},
                   {'kind': 'check'}],
                  [['vector', '5000', '40', '', '', '', None], ['insert', '3500', '80', '100', '', '', None],
                   ['Buffer', '', '', '', '', '2', None], ['Water', '', '', '', '', '=20-SUM(F1:F3)', None]])
    out = shown(moclo)
    assert out[0][4] == '132' and out[0][5] == '' and out[1][5] == '1.85' and out[3][5] == ''
    moclo['rows'][0]['cells'][3] = '66'
    out = shown(moclo)
    assert out[0][5] == '2' and out[3][5] == '14.15'


def test_a_blank_amount_in_a_row_in_use_is_still_to_come():
    protocol = table([{'kind': 'text'}, {'kind': 'number'}], [['Buffer', '2'], ['Vector', ''], ['', ''], ['Water', '=20-SUM(B1:B3)']])
    assert [r[1] for r in shown(protocol)] == ['2', '', '', '']
    protocol['rows'][1]['cells'][1] = '3'
    assert [r[1] for r in shown(protocol)] == ['2', '3', '', '15']


def test_errors_and_ticks():
    assert shown(table(['number'], [['=A1']])) == [['#CYCLE']]
    assert shown(table(['number', 'number'], [['1', '=A1/0']])) == [['1', '#DIV/0']]
    assert shown(table(['number'], [['=Z9']])) == [['#REF']]
    assert shown(table(['number'], [['=1+']]))[0][0].startswith('#')
    assert shown(table(['check', 'number'], [[{'by': 'ana'}, '=SUM(A1:A2)'], [None, '']])) == [['1', '1'], ['0', '']]


def test_numbers_are_written_as_the_page_writes_them():
    assert sheet.show(0.1 + 0.2) == '0.3'
    assert sheet.show(0.004321) == '0.0043'
    assert sheet.col_name(27) == 'AB'
    assert [sheet.js_number(x) for x in (132.0, 1e-7, 1.5e16, 1e21, -0.5, 0.000001)] == \
        ['132', '1e-7', '15000000000000000', '1e+21', '-0.5', '0.000001']
    assert shown(table(['number'], [['=2^0.5*2^0.5'], ['=(0-8)^0.5'], ['=0^-1']])) == [['2'], ['#NUM'], ['#NUM']]
