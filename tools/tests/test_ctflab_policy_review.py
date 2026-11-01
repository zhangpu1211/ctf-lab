"""离线跨节点策略闭合与假阳性边界；不运行网络探测。"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import canonical,ContractError
from ctflab_guest_policy import compile_policy
from ctflab_policy_review import review,main
from test_ctflab_guest_policy import envelope
from test_ctflab_guest_routes import definition,recompile


def bundle():
    router=envelope();router['flows'][0]['ports']=[80]
    router['compiled']=compile_policy(router['plan'],router['node'],router['devices'],router['flows'])
    client=definition();server=definition('server')
    for value in (client,server):value['plan']=router['plan'];recompile(value)
    return router['plan'],[router,client,server]


class PolicyReviewTests(unittest.TestCase):
    def test_complete_bidirectional_declarations_remain_unverified(self):
        plan,policies=bundle();result=review(plan,policies)
        self.assertTrue(result['declarations_complete']);self.assertEqual(result['findings'],[])
        self.assertFalse(result['executed']);self.assertFalse(result['isolation_verified'])
        self.assertFalse(result['service_verified']);self.assertEqual(len(result['paths']),1)
        self.assertEqual(len(result['shared_networks']),2)
        self.assertEqual(result['review_sha256'],hashlib.sha256(canonical({k:v for k,v in result.items() if k!='review_sha256'}).encode()).hexdigest())
        self.assertEqual(review(plan,list(reversed(policies))),result)

    def test_router_allow_without_terminals_is_incomplete(self):
        plan,policies=bundle();result=review(plan,policies[:1])
        self.assertFalse(result['declarations_complete'])
        self.assertEqual({v['node'] for v in result['findings']},{'client','server'})
        self.assertEqual({v['code'] for v in result['findings']},{'endpoint-policy-missing'})

    def test_terminal_narrower_protocol_and_direction_are_detected(self):
        for changes in ({'ports':[443]},{'protocol':'udp'},
                        {'source':{'node':'server','interface':'eth0'},'destination':{'node':'client','interface':'eth0'}}):
            with self.subTest(changes=changes):
                plan,policies=bundle();policies[1]['endpoint']['flows'][0].update(changes);recompile(policies[1])
                result=review(plan,policies)
                self.assertFalse(result['declarations_complete'])
                self.assertIn('endpoint-flow-missing-or-narrower',{v['code'] for v in result['findings']})

    def test_missing_return_route_is_detected_without_suggesting_changes(self):
        plan,policies=bundle();policies[2]['endpoint']={'routes':[],'flows':[]};recompile(policies[2])
        before=copy.deepcopy(policies);result=review(plan,policies)
        self.assertIn('endpoint-return-route-missing-or-different',{v['code'] for v in result['findings']})
        self.assertFalse(result['declarations_complete']);self.assertEqual(policies,before)

    def test_terminal_allow_without_router_not_counted_as_working_path(self):
        plan,policies=bundle();result=review(plan,policies[1:])
        self.assertEqual(result['paths'],[]);self.assertFalse(result['declarations_complete'])
        self.assertEqual({v['code'] for v in result['findings']},{'router-flow-missing-or-narrower'})

    def test_extra_endpoint_port_not_hidden_by_partial_router_allow(self):
        plan,policies=bundle();policies[1]['endpoint']['flows'][0]['ports']=[80,443];recompile(policies[1])
        result=review(plan,policies)
        self.assertTrue(result['paths'][0]['declarations_complete'])
        self.assertFalse(result['declarations_complete'])
        self.assertIn('router-flow-missing-or-narrower',{v['code'] for v in result['findings']})

    def test_duplicate_policy_mixed_instance_and_compiled_tamper_refused(self):
        plan,policies=bundle()
        for changed in ([policies[0],policies[0]],[envelope()],
                        [dict(policies[0],compiled=dict(policies[0]['compiled'],policy_sha256='0'*64))]):
            with self.assertRaises(ContractError):review(plan,changed)

    def test_empty_review_never_proves_isolation(self):
        plan,_=bundle();result=review(plan,[])
        self.assertFalse(result['declarations_complete']);self.assertFalse(result['isolation_verified'])

    def test_cli_new_output_only_and_incomplete_exit_code(self):
        plan,policies=bundle()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();(root/'plan.json').write_text(json.dumps(plan));args=['--plan',str(root/'plan.json')]
            for index,value in enumerate(policies):
                path=root/f'policy-{index}.json';path.write_text(json.dumps(value));args+=['--policy',str(path)]
            output=root/'report.json';args+=['--output',str(output)]
            self.assertEqual(main(args),0);before=output.read_bytes()
            self.assertEqual(main(args),2);self.assertEqual(output.read_bytes(),before)
            self.assertEqual(main(['--plan',str(root/'plan.json'),'--output',str(root/'incomplete.json')]),2)
            self.assertFalse(json.loads((root/'incomplete.json').read_text())['executed'])


if __name__=='__main__':unittest.main()
