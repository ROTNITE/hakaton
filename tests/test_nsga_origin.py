import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest

from controller.vendor import nsga2_v052 as port


class OptimizerOriginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).parents[1]
        cls.origin=json.loads((cls.root/'controller/vendor/nsga2-origin.json').read_text(encoding='utf-8'))
        spec=importlib.util.spec_from_file_location('original_nsga_test_reference',cls.root/cls.origin['source'])
        cls.original=importlib.util.module_from_spec(spec);sys.modules[spec.name]=cls.original
        spec.loader.exec_module(cls.original)

    def test_original_and_imported_bytes_match_the_declared_hash(self):
        for key in ('source','destination'):
            self.assertEqual(hashlib.sha256((self.root/self.origin[key]).read_bytes()).hexdigest(),self.origin['sha256'])
        self.assertFalse(self.origin['modified'])

    def test_known_pareto_front_and_dominated_layer(self):
        population=[port.Individual(i,f=f) for i,f in enumerate(((1,4),(2,2),(4,1),(3,4)))]
        fronts=port.assign_fronts(population)
        self.assertEqual(set(fronts[0]),{0,1,2});self.assertEqual(fronts[1],[3])

    def test_same_known_problem_matches_upstream_for_three_optimizer_seeds(self):
        def solve(module,seed):
            def init(rng):
                result=list(range(7));rng.shuffle(result);return result
            def evaluate(genome):
                distance=sum(abs(a-b) for a,b in zip([0,*genome],genome))
                urgency=sum((i+1)*(7-task) for i,task in enumerate(genome))
                return distance,urgency
            def mutate(genome,rng):
                result=genome[:]
                if rng.random()<.8:
                    a,b=rng.sample(range(len(result)),2);result[a],result[b]=result[b],result[a]
                return result
            front,stats=module.run_nsga2(init,evaluate,module.order_crossover,mutate,pop_size=20,generations=8,seed=seed)
            stats.pop('wall_ms')
            return [(tuple(i.genome),i.f,i.rank,i.crowd) for i in front],stats
        for seed in (7,42,2026):
            with self.subTest(seed=seed):self.assertEqual(solve(port,seed),solve(self.original,seed))


if __name__=='__main__':unittest.main()
