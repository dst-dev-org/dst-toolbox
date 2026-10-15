"""Independent syntax cases for writes, Class maps, alias resolution and lexical guards."""
import unittest
from test_extraction import ExtractorAssertions


class Stage2Tests(ExtractorAssertions, unittest.TestCase):
    def records(self, facts, kind):
        return [r for r in facts['records'] if r['kind'] == kind]

    def test_constructor_fields_are_writes_not_lifetime_types(self):
        data=b'''local C=Class(function(self)
 self.count=3
 self.count="later"
 self.callback=nil
 self.map={}
 self.map[key]=1
 local self={};self.fake=7
end)
function C:Use() self.count=self.count-1 end
'''
        facts,_=self.extract(data)
        fields=[s for s in facts['symbols'] if s['kind']=='field']
        self.assertEqual({s['name'] for s in fields}, {'count','callback','map'})
        self.assertEqual(len([s for s in fields if s['name']=='count']),1)
        writes=[r['data'] for r in self.records(facts,'assignment') if r['data']['target']=='self.count']
        self.assertEqual([(r['expression'],r['literal_kind']) for r in writes], [('3','number'),('"later"','string'),('self.count-1','nonliteral')])
        self.assertTrue(all(s['base_expression'] is None for s in fields))

    def test_class_properties_resolved_unresolved_and_ambiguous(self):
        data=b'''local function callback(self,value,old) end
local function other(self) end
if flag then callback=other end
local C=Class(function(self) self.value=0 end,nil,{
 value=callback,
 missing=external,
 inline=function(self) end,
})
'''
        facts,_=self.extract(data)
        properties=self.records(facts,'property_callback')
        states={r['data']['callback_expression']:r['data']['resolution'] for r in properties}
        self.assertEqual(states['callback']['state'],'ambiguous')
        self.assertEqual(set(states['callback']['candidates']), {'test.lua#module/function:callback','test.lua#module/function:other'})
        self.assertEqual(states['external']['state'],'unresolved')
        self.assertEqual(states['function(self) end']['state'],'resolved')
        self.assertEqual(len([s for s in facts['symbols'] if s['kind']=='field' and s['name']=='value']),1)

    def test_property_initializer_uses_outer_local_before_new_shadow(self):
        data=b'''local function setter() end
do
 local setter,C=external,Class(function(self) end,nil,{value=setter})
end
'''
        facts,_=self.extract(data)
        prop=self.records(facts,'property_callback')[0]
        self.assertEqual(prop['data']['resolution']['symbol_id'],'test.lua#module/function:setter')

    def test_method_alias_copies_explicit_parameters_and_keeps_original_target(self):
        data=b'''local C=Class(function(self) end)
function C:Close(reason,...) end
C.OnRemoveFromEntity=C.Close
C.Second=C.OnRemoveFromEntity
'''
        facts,_=self.extract(data)
        aliases=self.records(facts,'method_alias')
        self.assertEqual(len(aliases),2)
        for r in aliases:
            self.assertEqual(r['data']['resolution']['symbol_id'],'test.lua#C/method:Close')
            target=next(s for s in facts['symbols'] if s['id']==r['data']['target_symbol_id'])
            self.assertEqual(target['calling'],'colon')
            self.assertEqual(target['parameters'],[{'name':'reason','kind':'named'},{'name':'...','kind':'vararg'}])

    def test_conditional_method_targets_do_not_choose_last_definition(self):
        data=b'''local C=Class(function(self) end)
function C:Close() end
if flag then function C:Close(reason) end end
C.Removed=C.Close
'''
        facts,_=self.extract(data)
        alias=self.records(facts,'method_alias')[0]
        self.assertEqual(alias['data']['resolution']['state'],'ambiguous')
        self.assertEqual(set(alias['data']['resolution']['candidates']), {'test.lua#C/method:Close','test.lua#C/method:Close@2'})
        target=next(s for s in facts['symbols'] if s['name']=='Removed')
        self.assertEqual(target['parameters'],[])
        self.assertEqual(target['calling'],'none')

    def test_overwritten_function_or_class_member_is_not_resolved(self):
        data=b'''local function setter() end
setter=external
local C=Class(function(self) end,nil,{value=setter})
function C:Close() end
C.Close=external
C.Removed=C.Close
'''
        facts,_=self.extract(data)
        self.assertEqual(self.records(facts,'property_callback')[0]['data']['resolution']['state'],'unresolved')
        self.assertFalse(self.records(facts,'method_alias'))
        self.assertFalse(any(s['name']=='Removed' for s in facts['symbols']))

    def test_nested_elseif_else_and_early_return_comments(self):
        data=b'''local function work(a,b)
 if a==nil then return false end
 if b then
  -- then
  value=1
 elseif a>2 then
  -- elseif
  value=2
 else
  -- else
  value=3
 end
 return true,value
end
'''
        facts,_=self.extract(data)
        expected={
            '-- then':[('a==nil','after-return'),('b','then')],
            '-- elseif':[('a==nil','after-return'),('b','else'),('a>2','elseif')],
            '-- else':[('a==nil','after-return'),('b','else'),('a>2','else')],
        }
        for r in self.records(facts,'comment'):
            self.assertEqual([(g['expression'],g['branch']) for g in r['guards']], expected[r['data']['text']])
        final=self.records(facts,'return')[-1]
        self.assertEqual(final['data'], {'expressions':['true','value'],'implicit':False})
        self.assertEqual([(g['expression'],g['branch']) for g in final['guards']], [('a==nil','after-return')])

    def test_closure_body_does_not_inherit_definition_time_guard(self):
        data=b'''if flag then
 local callback=function()
  -- runs later
  return 1
 end
end
'''
        facts,_=self.extract(data)
        assignment=next(r for r in self.records(facts,'assignment') if r['data']['target']=='callback')
        self.assertEqual([(g['expression'],g['branch']) for g in assignment['guards']], [('flag','then')])
        self.assertEqual(self.records(facts,'comment')[0]['guards'],[])
        self.assertEqual(self.records(facts,'return')[0]['guards'],[])

    def test_loop_headers_repeat_and_nested_function_boundaries(self):
        data=b'''while active do
 -- while
end
repeat
 -- repeat
 local x=1
until ready
for i=1,3 do
 -- numeric
end
for k,v in pairs(t) do
 -- generic
end
'''
        facts,_=self.extract(data)
        guards={r['data']['text']:r['guards'] for r in self.records(facts,'comment')}
        self.assertEqual(guards['-- while'][0]['expression'],'active')
        self.assertEqual(guards['-- repeat'][0]['expression'],'ready')
        self.assertEqual(guards['-- numeric'][0]['expression'].strip(),'i=1,3')
        self.assertEqual(guards['-- generic'][0]['expression'].strip(),'pairs(t)')
        self.assertTrue(all(g[0]['branch']=='loop' for g in guards.values()))

    def test_multiple_assignment_does_not_invent_extra_call_results(self):
        facts,_=self.extract(b'local a,b=external()\nlocal c,d=1\nlocal e,f=...\n')
        writes={r['data']['target']:r['data'] for r in self.records(facts,'assignment')}
        self.assertNotIn('b',writes)
        self.assertNotIn('f',writes)
        self.assertNotIn('d',writes)
        self.assertTrue(any(d['code']=='implicit-assignment-value-deferred' for d in facts['coverage']['diagnostics']))
        self.assertTrue(any(d['code']=='expanded-assignment-deferred' for d in facts['coverage']['diagnostics']))

    def test_parallel_method_swap_and_direct_function_assignment(self):
        data=b'''local C=Class(function(self) end)
function C:First(a) end
function C:Second(b) end
C.First,C.Second=C.Second,C.First
C.Direct=function(z,...) end
C.Alias=C.Direct
'''
        facts,_=self.extract(data)
        aliases=self.records(facts,'method_alias')
        self.assertEqual([r['data']['resolution']['symbol_id'] for r in aliases],
                         ['test.lua#C/method:Second','test.lua#C/method:First','test.lua#C/method:Direct'])
        direct=next(s for s in facts['symbols'] if s['name']=='Direct')
        self.assertEqual(direct['calling'],'plain')
        self.assertEqual(direct['parameters'],[{'name':'z','kind':'named'},{'name':'...','kind':'vararg'}])

    def test_two_class_initializers_keep_separate_property_mappings(self):
        facts,_=self.extract(b'''local function a() end
local function b() end
local A,B=Class(function(self) end,nil,{x=a}),Class(function(self) end,nil,{y=b})
''')
        properties=self.records(facts,'property_callback')
        self.assertEqual({(r['subject_symbol_id'],r['data']['callback_expression']) for r in properties},
                         {('test.lua#module/class:A','a'),('test.lua#module/class:B','b')})

    def test_break_path_does_not_prove_early_return(self):
        facts,_=self.extract(b'''while active do
 if a then
  if stop then break end
  return 1
 end
 -- continuation
end
''')
        comment=self.records(facts,'comment')[0]
        self.assertFalse(any(g['branch']=='after-return' for g in comment['guards']))
        self.assertEqual([(g['expression'],g['branch']) for g in comment['guards']], [('active','loop')])

    def test_crlf_unicode_guard_and_conditional_local_declaration(self):
        data='if label == "耐久" then\r\n local function work() return 1 end\r\n -- WARNING: 条件\r\nend\r\n'.encode('utf-8')
        facts,anchors=self.extract(data)
        assignment=self.records(facts,'assignment')[0]
        self.assertEqual(assignment['subject_symbol_id'],'test.lua#module/function:<chunk>')
        self.assertEqual(assignment['data']['target'],'work')
        self.assertEqual([(g['expression'],g['branch']) for g in assignment['guards']], [('label == "耐久"','then')])
        guard_anchor=anchors[assignment['guards'][0]['anchor_id']]
        self.assertEqual(data[guard_anchor['start']['byte']:guard_anchor['end']['byte']], 'label == "耐久"'.encode('utf-8'))
        self.assertEqual(self.records(facts,'return')[0]['guards'],[])
        self.assertTrue(self.records(facts,'comment')[0]['data']['text'].endswith('\r'))

    def test_unknown_class_and_dynamic_properties_preserve_limitations(self):
        data=b'''local C=Class(Base,constructor,props)
local D=Class(function(self) end,nil,props)
local E=Class(function(self) end,nil,{[key]=external})
'''
        facts,_=self.extract(data)
        self.assertFalse(any(s['kind']=='class' and s['name']=='C' for s in facts['symbols']))
        self.assertFalse(self.records(facts,'property_callback'))
        codes={d['code'] for d in facts['coverage']['diagnostics']}
        self.assertTrue({'unresolved-class-overload','dynamic-properties-deferred','dynamic-property-key-deferred'} <= codes)
