import unittest
from src.lakehouse import DEFAULTS,validate_config,validate_identity,compute_evidence
class ConfigTests(unittest.TestCase):
    def test_project_parameters_preserve_temporary_authorized_identity(self):
        values=validate_identity({'equipo':'3','equipo_recursos':'5','compute_mode':'serverless'})
        self.assertEqual((values['equipo'],values['equipo_recursos']),('03','05'))
        for change in ({'equipo':'04'},{'equipo_recursos':'03'},{'compute_mode':'inventado'},{'source_root':'s3://otro/'}):
            with self.subTest(change=change),self.assertRaises(ValueError):validate_identity(dict(values,**change))
    def test_compute_report_does_not_invent_classic_node_configuration(self):
        class Spark:version='4.0.0'
        report=compute_evidence(Spark(),'serverless')
        self.assertEqual(report['spark'],'4.0.0')
        self.assertEqual(report['autorizacion_docente_serverless'],'PENDIENTE')
        self.assertNotIn('i3.xlarge',str(report))
        self.assertIn('librerias_instaladas',report)
    def test_only_own_catalog_and_prefixes_are_allowed(self):
        values=dict(DEFAULTS,fecha_corte='2026-11-20')
        self.assertEqual(validate_config(values)['catalog'],'lakehouse_equipo5')
        for field,value in [('catalog','otro'),('source_path',DEFAULTS['source_path']+'../otro/'),('gold_root','s3://otro/'),('umbral_q','-1')]:
            with self.subTest(field=field),self.assertRaises(ValueError):validate_config(dict(values,**{field:value}))
