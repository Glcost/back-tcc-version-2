"""Concurrency tests; run only against the disposable CI PostgreSQL service."""
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import unittest
from urllib.parse import urlsplit
from uuid import uuid4

DSN=os.environ.get('ROAR_TEST_DATABASE_URL','')


@unittest.skipUnless(DSN,'Disposable PostgreSQL URL not configured')
class PostgresConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        target=urlsplit(DSN)
        if target.hostname not in ('127.0.0.1','localhost') or target.path!='/roar_test' or os.environ.get('ROAR_ALLOW_DISPOSABLE_DB')!='yes':
            raise RuntimeError('Concurrency tests require an explicitly disposable local roar_test database')
        import psycopg
        cls.connect=staticmethod(lambda:psycopg.connect(DSN))

    def setUp(self):
        with self.connect() as db:
            db.execute('delete from aluno_palavras_pratica')
            db.execute('delete from roar_progress_requests')
            db.execute('delete from historico_desempenho')
            db.execute('delete from aluno_skins_lex')
            db.execute('update alunos set xp_total=500,skin_ativa_id=1 where id=17')

    def concurrent(self,operations):
        barrier=Barrier(len(operations))
        def execute(operation):
            with self.connect() as db:
                barrier.wait(timeout=10)
                return db.execute(*operation).fetchone()[0]
        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            return list(executor.map(execute,operations))

    def test_two_simultaneous_purchases_charge_once(self):
        results=self.concurrent([('select roar_shop_transaction(17,%s,2)',('comprar',))]*2)
        self.assertEqual(sorted(result.get('code','PURCHASED') for result in results),['PURCHASED','SKIN_ALREADY_OWNED'])
        with self.connect() as db:
            self.assertEqual(db.execute('select xp_total from alunos where id=17').fetchone()[0],400)
            self.assertEqual(db.execute('select count(*) from aluno_skins_lex where aluno_id=17').fetchone()[0],1)

    def test_two_simultaneous_completions_do_not_lose_xp(self):
        results=self.concurrent([('select roar_register_progress(17,%s,0,1,true,%s,\'[]\')',(activity,uuid4())) for activity in (1,2)])
        self.assertEqual(sum(result['data']['xp_ganho'] for result in results),100)
        with self.connect() as db:
            self.assertEqual(db.execute('select xp_total from alunos where id=17').fetchone()[0],600)
            self.assertEqual(db.execute('select count(*) from historico_desempenho where aluno_id=17').fetchone()[0],2)

    def test_completion_retry_in_parallel_does_not_duplicate_reward(self):
        attempt=uuid4()
        results=self.concurrent([('select roar_register_progress(17,1,0,1,true,%s,\'[]\')',(attempt,))]*2)
        with self.connect() as db:
            self.assertEqual(db.execute('select xp_total from alunos where id=17').fetchone()[0],550)
            self.assertEqual(db.execute('select count(*) from historico_desempenho where aluno_id=17').fetchone()[0],1)
            self.assertEqual(db.execute('select count(*) from roar_progress_requests where aluno_id=17').fetchone()[0],1)

    def test_purchase_and_reward_share_balance_lock(self):
        self.concurrent([
            ('select roar_shop_transaction(17,%s,2)',('comprar',)),
            ('select roar_register_progress(17,1,0,1,true,%s,\'[]\')',(uuid4(),)),
        ])
        with self.connect() as db:
            self.assertEqual(db.execute('select xp_total from alunos where id=17').fetchone()[0],450)


if __name__=='__main__': unittest.main()
