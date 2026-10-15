"""Independent call/relationship cases exercising the actual Lua parser."""
import unittest
from test_extraction import ExtractorAssertions


class Stage3Tests(ExtractorAssertions, unittest.TestCase):
    def records(self, facts, kind):
        return [r for r in facts['records'] if r['kind']==kind]

    def test_bracket_callee_chain_and_all_nested_calls(self):
        data=b'local function get(x) return x end\nget(1).components["health"]:Do(get(2)); p[2](t,v,old)'
        facts,anchors=self.extract(data)
        calls=self.records(facts,'call')
        self.assertEqual(len(calls),4)
        self.assertEqual(sorted((r['data']['callee'],r['data']['arguments']) for r in calls if r['data']['callee']=='get'), [('get',['1']),('get',['2'])])
        do=next(r for r in calls if r['data']['callee']=='Do')
        self.assertEqual(do['data']['receiver'],'get(1).components["health"]')
        p=next(r for r in calls if r['data']['callee']=='p[2]')
        a=anchors[p['anchor_id']]
        self.assertEqual(data[a['start']['byte']:a['end']['byte']],b'p[2](t,v,old)')
        read=self.records(facts,'component_access')[0]
        self.assertEqual(read['data']['receiver'],'get(1)')
        self.assertEqual(read['data']['literal_name'],'health')

    def test_string_table_and_parenthesized_function_arguments(self):
        facts,_=self.extract(b'local function f(x) end\nf "hello"; f {x=1}; (f)(2)')
        calls=self.records(facts,'call')
        self.assertEqual([r['data']['arguments'] for r in calls],[['"hello"'],['{x=1}'],['2']])
        self.assertTrue(all(r['data']['resolution']['state']=='resolved' for r in calls))

    def test_forward_self_method_and_shadowed_receiver(self):
        facts,_=self.extract(b'''local C=Class(function(self) end)
function C:First() self:Later(2); local self={};self:Later(3) end
function C:Later(x) end
''')
        calls=[r for r in self.records(facts,'call') if r['data']['callee']=='Later']
        self.assertEqual(calls[0]['data']['resolution']['symbol_id'],'test.lua#C/method:Later')
        self.assertEqual(calls[1]['data']['resolution']['state'],'unresolved')

    def test_call_resolution_three_states_and_lexical_scopes(self):
        facts,_=self.extract(b'''local function f() end
local function g() end
f(); if flag then f=g end; f(); f=unknown; f()
do local function f(x) end; f(1) end
''')
        calls=[r for r in self.records(facts,'call') if r['data']['callee']=='f']
        self.assertEqual([r['data']['resolution']['state'] for r in calls],['resolved','ambiguous','unresolved','resolved'])
        self.assertEqual(calls[-1]['data']['resolution']['symbol_id'],'test.lua#module/block:2/function:f')

    def test_event_literals_lua51_escapes_and_listener_source(self):
        facts,_=self.extract(b'inst:PushEvent("a\\110b",nil);inst:ListenForEvent([=[\r\ntick]=],cb,other);inst:PushEvent(name,payload)')
        events=self.records(facts,'event_emit')+self.records(facts,'event_listen')
        self.assertEqual([r['data']['literal_name'] for r in events],['anb',None,'tick'])
        listen=self.records(facts,'event_listen')[0]
        self.assertIsNone(listen['data']['payload_expression'])
        self.assertEqual(listen['data']['callback_expression'],'cb')
        call=next(r for r in self.records(facts,'call') if r['data']['callee']=='ListenForEvent')
        self.assertEqual(call['data']['arguments'][-1],'other')

    def test_prefab_registration_inline_factory_dynamic_and_shadow(self):
        facts,_=self.extract(b'''Prefab("a",function(inst) end)
Prefab(name,unknown)
local Prefab=function() end
Prefab("fake",unknown)
''')
        prefabs=self.records(facts,'prefab_registration')
        self.assertEqual(len(prefabs),2)
        self.assertEqual(prefabs[0]['data']['resolution']['state'],'resolved')
        self.assertIsNone(prefabs[1]['data']['literal_name'])
        self.assertEqual(prefabs[1]['data']['resolution']['state'],'unresolved')

    def test_component_brackets_conditions_write_and_replica_exclusion(self):
        facts,_=self.extract(b'''if inst.components.health~=nil then inst.components[name]:Do() end
inst["components"]["meter"]:Use()
inst.components.health=nil
inst.replica.health:Get()
inst:AddComponent("armor"); inst:RemoveComponent(name)
''')
        records=self.records(facts,'component_access')
        self.assertEqual([(r['data']['literal_name'],r['data']['operation']) for r in records],[('health','read'),(None,'read'),('meter','read'),('armor','add'),(None,'remove')])
        self.assertTrue(any(d['code']=='direct-component-write' for d in facts['coverage']['diagnostics']))
        self.assertEqual(facts['coverage']['status'],'partial')

    def test_conditional_calls_closure_boundary_and_utf8_crlf(self):
        for nl in ('\n','\r\n'):
            data=nl.join(['local function f() end','if flag then',' f()',' local cb=function() inst:PushEvent("中文",{}) end','end','']).encode('utf-8')
            facts,_=self.extract(data)
            f=next(r for r in self.records(facts,'call') if r['data']['callee']=='f')
            self.assertEqual([(g['expression'],g['branch']) for g in f['guards']],[('flag','then')])
            event=self.records(facts,'event_emit')[0]
            self.assertEqual(event['guards'],[])
            self.assertEqual(event['data']['literal_name'],'中文')

    def test_literal_property_key_member_alias_and_bracket_call(self):
        facts,_=self.extract(b'''local function setter() end
local C=Class(function(self) self["value"]=0 end,nil,{["value"]=setter})
function C:Close(reason) end
C["Removed"]=C["Close"]
C["Removed"](1)
''')
        prop=self.records(facts,'property_callback')[0]
        self.assertEqual(prop['data']['resolution']['symbol_id'],'test.lua#module/function:setter')
        alias=self.records(facts,'method_alias')[0]
        self.assertEqual(alias['data']['resolution']['symbol_id'],'test.lua#C/method:Close')
        call=next(r for r in self.records(facts,'call') if r['data']['callee']=='C["Removed"]')
        self.assertEqual(call['data']['resolution']['symbol_id'],'test.lua#C/method:Close')

    def test_short_circuit_guards_and_function_body_boundary(self):
        facts,_=self.extract(b'''local function f() end
local a=flag and f()
local b=ready or f()
local c=flag and function() f() end
''')
        calls=[r for r in self.records(facts,'call') if r['data']['callee']=='f']
        self.assertEqual([[(g['expression'],g['branch']) for g in r['guards']] for r in calls],[[('flag','then')],[('ready','else')],[]])

    def test_provable_elseif_and_else_continuation(self):
        facts,_=self.extract(b'''local function f(a,b)
 if a then return elseif b then return end
 inst:PushEvent("after")
end
local function g(a)
 if a then inst:PushEvent("before") else return end
 inst:PushEvent("survives")
end
local function h(a)
 if a then return else inst:PushEvent("else") end
 inst:PushEvent("continues")
end
''')
        events={r['data']['literal_name']:r for r in self.records(facts,'event_emit')}
        self.assertEqual([(g['expression'],g['branch']) for g in events['after']['guards']],[('a','after-return'),('b','after-return')])
        self.assertEqual([(g['expression'],g['branch']) for g in events['survives']['guards']],[('a','then')])
        self.assertEqual([(g['expression'],g['branch']) for g in events['continues']['guards']],[('a','after-return')])

    def test_short_circuit_component_guard_uses_access_location(self):
        facts,_=self.extract(b'if flag and inst.components.health then inst.components.health:Do() end')
        access=self.records(facts,'component_access')[0]
        self.assertEqual([(g['expression'],g['branch']) for g in access['guards']],[('flag','then')])

    def test_large_literal_table_preserves_trivia_and_return_expression(self):
        data=b'-- WARNING: large layout\nreturn {'+b','.join(b'{x=1,y=2}' for _ in range(10000))+b'}\n'
        facts,anchors=self.extract(data)
        self.assertEqual(len(self.records(facts,'comment')),1)
        returned=self.records(facts,'return')[0]
        self.assertEqual(returned['data']['expressions'][0].encode('utf-8'),data[data.index(b'{'):data.rfind(b'}')+1])
        a=anchors[returned['anchor_id']]
        self.assertEqual(data[a['start']['byte']:a['end']['byte']],data[data.index(b'return'):data.rfind(b'}')+1])


if __name__=='__main__': unittest.main()
