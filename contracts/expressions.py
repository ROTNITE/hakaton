"""Bounded JSON predicates from Appendix A §1.9; never executes host code.

The normative list on page 14 contains 15 operators. Literal and path leaves
are separate node forms. Missing public facts remain UNKNOWN, not false.
"""
from __future__ import annotations

from copy import deepcopy
import math
import re

from contracts.protocol import OBSERVATION,AGENT,ZONE

OPERATORS=('and','or','not','eq','ne','lt','le','gt','ge','exists','in','all','any','count','sum')


class ExpressionError(ValueError):pass


class _Unknown:
    def __repr__(self):return 'UNKNOWN'
    def __bool__(self):raise TypeError('UNKNOWN must be handled explicitly')


UNKNOWN=_Unknown()
SCOPES={'observation':set(OBSERVATION['properties'])|{'metaevolution'},
        'agent':set(AGENT['properties'])|{'freshness'},
        'zone':set(ZONE['properties']),
        'mission':{'id','objectives','priorities','directives','constraints','status','termination'},
        'execution_rules':{'observation','execution','parameters'}}
NAME=re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')


def _boolean(value):
    if value is UNKNOWN or type(value) is bool:return value
    raise ExpressionError('Boolean expression required')


def _numeric(value):
    try:valid=type(value) in (int,float) and math.isfinite(value)
    except OverflowError:valid=False
    if not valid:
        raise ExpressionError('Finite numeric operand required; boolean is not numeric')
    return value


def _same(a,b,visit=None):
    if visit:visit()
    if a is UNKNOWN or b is UNKNOWN:return UNKNOWN
    if (type(a) is bool and type(b) in (int,float)) or (type(b) is bool and type(a) in (int,float)):
        raise ExpressionError('Boolean and numeric values cannot be compared as numbers')
    if isinstance(a,dict) and isinstance(b,dict):
        return a.keys()==b.keys() and all(_same(a[k],b[k],visit) for k in a)
    if isinstance(a,list) and isinstance(b,list):
        return len(a)==len(b) and all(_same(x,y,visit) for x,y in zip(a,b))
    if type(a) in (int,float):_numeric(a)
    if type(b) in (int,float):_numeric(b)
    return a==b


def _literal(value,depth=0,counter=None):
    counter=[0] if counter is None else counter;counter[0]+=1
    if depth>16 or counter[0]>4096:raise ExpressionError('Literal exceeds size/depth budget')
    if value is None or type(value) in (bool,str):return
    if type(value) in (int,float):_numeric(value);return
    if isinstance(value,list):
        for item in value:_literal(item,depth+1,counter)
    elif isinstance(value,dict) and all(isinstance(k,str) for k in value):
        for item in value.values():_literal(item,depth+1,counter)
    else:raise ExpressionError('Literal must be JSON data')


def _validate(node,variables=frozenset(),depth=1,counter=None):
    counter=[0] if counter is None else counter;counter[0]+=1
    if depth>16 or counter[0]>256:raise ExpressionError('Expression exceeds depth 16 / 256 nodes')
    if not isinstance(node,dict):raise ExpressionError('Expression node must be an object')
    def fields(required,optional=()):
        if not set(required)<=node.keys() or node.keys()-set(required)-set(optional):
            raise ExpressionError('Invalid node fields')
    if 'value' in node:
        fields(('value',));_literal(node['value']);return
    if 'path' in node:
        fields(('path',));path=node['path']
        if not isinstance(path,str) or not path or len(path)>1024:raise ExpressionError('Invalid public path')
        parts=path.split('.')
        if any(not part or not (NAME.fullmatch(part.lstrip('$')) or part.isdecimal()) for part in parts):
            raise ExpressionError('Invalid path segment')
        if parts[0].startswith('$') and parts[0][1:] not in variables:
            raise ExpressionError('Undeclared quantifier variable')
        if any('$' in part for part in parts[1:]):raise ExpressionError('Variable must be the path root')
        return
    op=node.get('op')
    if op not in OPERATORS:raise ExpressionError('Unsupported predicate operator')
    children=[];nested=variables
    if op in ('and','or'):
        fields(('op','args'))
        if not isinstance(node['args'],list):raise ExpressionError('args must be an array')
        children=node['args']
    elif op in ('not','exists'):
        fields(('op','arg'));children=[node['arg']]
        if op=='exists' and (not isinstance(node['arg'],dict) or set(node['arg'])!={'path'}):
            raise ExpressionError('exists requires a path node')
    elif op in ('all','any','count','sum'):
        required=('op','items','var')+(() if op=='count' else ('select',) if op=='sum' else ('where',))
        fields(required,('where',) if op=='count' else ())
        var=node['var']
        if not isinstance(var,str) or not NAME.fullmatch(var):
            raise ExpressionError('Invalid quantifier variable')
        _validate(node['items'],variables,depth+1,counter)
        nested=variables|{var}
        children=[node[key] for key in ('where','select') if key in node]
    else:
        fields(('op','left','right'));children=[node['left'],node['right']]
    for child in children:_validate(child,nested,depth+1,counter)
    def kind(child):
        if 'path' in child:return 'unknown'
        if 'value' in child:
            item=child['value']
            return ('boolean' if type(item) is bool else 'number' if type(item) in (int,float) else
                    'array' if isinstance(item,list) else 'other')
        return 'number' if child['op'] in ('count','sum') else 'boolean'
    def expect(child,expected):
        if kind(child) not in ('unknown',expected):raise ExpressionError('Incompatible declared operand type')
    if op in ('and','or'):
        for child in children:expect(child,'boolean')
    elif op=='not':expect(node['arg'],'boolean')
    elif op in ('all','any','count','sum'):
        expect(node['items'],'array')
        if 'where' in node:expect(node['where'],'boolean')
        if 'select' in node:expect(node['select'],'number')
    elif op=='in':expect(node['right'],'array')
    elif op in ('lt','le','gt','ge'):
        expect(node['left'],'number');expect(node['right'],'number')


class Expression:
    def __init__(self,node):
        _validate(node);self._node=deepcopy(node)

    def evaluate(self,context,*,scope='observation',extension_roots=(),max_items=20000,max_work=100000):
        if scope not in SCOPES or not isinstance(context,dict):raise ExpressionError('Invalid public scope')
        allowed=SCOPES[scope]|set(extension_roots)
        root={k:v for k,v in context.items() if k in allowed and not k.startswith('_')}
        if scope=='execution_rules' and isinstance(root.get('observation'),dict):
            root['observation']={k:v for k,v in root['observation'].items() if k in SCOPES['observation']}
        work=0

        def consume():
            nonlocal work
            work+=1
            if work>max_work:raise ExpressionError('Evaluation work budget exceeded')

        def path(name,variables):
            parts=name.split('.')
            if parts[0].startswith('$'):current=variables[parts.pop(0)[1:]]
            else:current=root
            for part in parts:
                if isinstance(current,dict):
                    if part not in current:return UNKNOWN
                    current=current[part]
                elif isinstance(current,list):
                    if not part.isdecimal():raise ExpressionError('Array path requires an index')
                    index=int(part)
                    if index>=len(current):return UNKNOWN
                    current=current[index]
                elif current is UNKNOWN:return UNKNOWN
                else:raise ExpressionError('Path traverses a non-container')
            return current

        def run(node,variables):
            nonlocal work
            work+=1
            if work>max_work:raise ExpressionError('Evaluation work budget exceeded')
            if 'value' in node:return node['value']
            if 'path' in node:return path(node['path'],variables)
            op=node['op']
            if op in ('and','or'):
                unknown=False
                for child in node['args']:
                    value=_boolean(run(child,variables))
                    if value is UNKNOWN:unknown=True
                    elif (op=='and' and value is False) or (op=='or' and value is True):return value
                return UNKNOWN if unknown else op=='and'
            if op=='not':
                value=_boolean(run(node['arg'],variables));return UNKNOWN if value is UNKNOWN else not value
            if op=='exists':return run(node['arg'],variables) is not UNKNOWN
            if op in ('all','any','count','sum'):
                items=run(node['items'],variables)
                if items is UNKNOWN:return UNKNOWN
                if not isinstance(items,list):raise ExpressionError('Quantifier items must be an array')
                if len(items)>max_items:raise ExpressionError('Quantifier array budget exceeded')
                unknown=False;total=0
                for item in items:
                    bindings={**variables,node['var']:item}
                    if op=='sum':
                        value=run(node['select'],bindings)
                        if value is UNKNOWN:unknown=True
                        else:total+=_numeric(value);_numeric(total)
                    else:
                        value=_boolean(run(node['where'],bindings)) if 'where' in node else True
                        if value is UNKNOWN:unknown=True
                        elif op=='all' and value is False:return False
                        elif op=='any' and value is True:return True
                        elif op=='count' and value is True:total+=1
                if unknown:return UNKNOWN
                return total if op in ('sum','count') else op=='all'
            left=run(node['left'],variables);right=run(node['right'],variables)
            if left is UNKNOWN or right is UNKNOWN:return UNKNOWN
            if op=='eq':return _same(left,right,consume)
            if op=='ne':return not _same(left,right,consume)
            if op=='in':
                if not isinstance(right,list):raise ExpressionError('in requires an array on the right')
                if len(right)>max_items:raise ExpressionError('Membership array budget exceeded')
                for item in right:
                    work+=1
                    if work>max_work:raise ExpressionError('Evaluation work budget exceeded')
                    if _same(left,item,consume):return True
                return False
            _numeric(left);_numeric(right)
            return {'lt':lambda:left<right,'le':lambda:left<=right,'gt':lambda:left>right,'ge':lambda:left>=right}[op]()
        result=run(self._node,{})
        return deepcopy(result) if isinstance(result,(dict,list)) else result


def evaluate(node,context,**options):return Expression(node).evaluate(context,**options)
