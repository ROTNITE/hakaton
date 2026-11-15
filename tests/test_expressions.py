import unittest
from contracts.expressions import Expression,ExpressionError,UNKNOWN,OPERATORS,evaluate


def value(x):return {'value':x}
def path(x):return {'path':x}
def binary(op,left,right):return {'op':op,'left':left,'right':right}


class PredicateTests(unittest.TestCase):
    def test_normative_operator_set_and_numeric_comparisons(self):
        self.assertEqual(set(OPERATORS),{'and','or','not','eq','ne','lt','le','gt','ge','exists','in','all','any','count','sum'})
        for op,expected in [('lt',True),('le',True),('gt',False),('ge',False),('eq',False),('ne',True)]:
            self.assertIs(evaluate(binary(op,value(.3),value(.55)),{}),expected)
        with self.assertRaises(ExpressionError):evaluate(binary('ge',value(True),value(0)),{})
        with self.assertRaises(ExpressionError):evaluate(binary('eq',value(True),value(1)),{})

    def test_three_valued_logic_and_null_existence(self):
        for op,known,expected in [('and',False,False),('and',True,UNKNOWN),('or',False,UNKNOWN),('or',True,True)]:
            self.assertIs(evaluate({'op':op,'args':[path('metrics.missing'),value(known)]},{}),expected)
        self.assertIs(evaluate({'op':'not','arg':path('metrics.missing')},{}),UNKNOWN)
        self.assertFalse(evaluate({'op':'exists','arg':path('metrics.missing')},{}))
        self.assertTrue(evaluate({'op':'exists','arg':path('metrics.x')},{'metrics':{'x':None}}))
        self.assertTrue(evaluate(binary('eq',path('metrics.x'),value(None)),{'metrics':{'x':None}}))

    def test_private_roots_and_host_attributes_are_not_visible(self):
        self.assertIs(evaluate(path('_truth.targets'),{'_truth':{'targets':[1]}}),UNKNOWN)
        self.assertIs(evaluate(path('network.__class__'),{'network':{}}),UNKNOWN)
        with self.assertRaises(ExpressionError):Expression({'op':'eval','value':'print(1)'})
        with self.assertRaises(ExpressionError):Expression(path('$undeclared.secret'))

    def test_quantifiers_count_sum_unknown_and_empty_arrays(self):
        for op,expected in [('all',True),('any',False),('count',0),('sum',0)]:
            expr={'op':op,'items':path('agents'),'var':'a'}
            if op in ('all','any'):expr['where']=value(True)
            if op=='sum':expr['select']=path('$a.energy')
            self.assertEqual(evaluate(expr,{'agents':[]}),expected)
        context={'agents':[{'energy':.3},{'energy':.6}]}
        expr={'op':'sum','items':path('agents'),'var':'a','select':path('$a.energy')}
        self.assertAlmostEqual(evaluate(expr,context),.9)
        context['agents'].append({});self.assertIs(evaluate(expr,context),UNKNOWN)
        count={'op':'count','items':path('agents'),'var':'a','where':binary('ge',path('$a.energy'),value(.5))}
        self.assertIs(evaluate(count,context),UNKNOWN)

    def test_declaration_and_work_limits(self):
        expression=value(True)
        for _ in range(18):expression={'op':'not','arg':expression}
        with self.assertRaises(ExpressionError):Expression(expression)
        with self.assertRaises(ExpressionError):Expression({'op':'and','args':[value(True)]*257})
        expression=Expression({'op':'sum','items':path('agents'),'var':'a','select':value(1)})
        with self.assertRaises(ExpressionError):expression.evaluate({'agents':[{}]*12},max_work=5)
        with self.assertRaises(ExpressionError):expression.evaluate({'agents':[{}]*12},max_items=10)
        with self.assertRaises(ExpressionError):Expression({'op':'and','args':[value(False),value(1)]})
        with self.assertRaises(ExpressionError):Expression(value(10**1000))
        membership=Expression(binary('in',value('missing'),path('agents')))
        with self.assertRaises(ExpressionError):membership.evaluate({'agents':['a']*12},max_items=10)
        nested=Expression(binary('eq',value([1]*100),value([1]*100)))
        with self.assertRaises(ExpressionError):nested.evaluate({},max_work=20)

    def test_scope_and_literal_membership(self):
        self.assertTrue(evaluate(binary('in',path('kind'),value(['ground','aerial'])),{'kind':'ground'},scope='agent'))
        self.assertIs(evaluate(path('metrics.x'),{'metrics':{'x':3}},scope='agent'),UNKNOWN)
        self.assertEqual(evaluate(path('parameters.x'),{'parameters':{'x':3}},scope='execution_rules'),3)
        expression=Expression(value([1,2]));result=expression.evaluate({});result.append(3)
        self.assertEqual(expression.evaluate({}),[1,2])


if __name__=='__main__':unittest.main()
