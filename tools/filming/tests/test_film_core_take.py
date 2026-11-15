from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from film_core_take import film_command


class CoreCameraAdapterTests(unittest.TestCase):
    def test_preserves_core_geometry_endpoint_and_controller_source(self):
        original=['UnrealEditor.exe','original.uproject','/Game/Maps/RescueQuarter','-MRCorePort=8130',
            '-MRLayoutFile=world.private.json','-MRCoreSource=source','-MRCorePython=python',
            '-MRCoreExitOnClose','-RenderOffscreen','-ResX=1600','-ResY=1000']
        result=film_command(original,Path('runtime'),Path('plan.json'),Path('capture'),1920,1080)
        self.assertEqual(original[1],'original.uproject')
        for value in ('-MRCorePort=8130','-MRLayoutFile=world.private.json','-MRCoreSource=source','-MRCorePython=python','-RenderOffscreen'):
            self.assertIn(value,result)
        self.assertNotIn('-MRCoreExitOnClose',result)
        self.assertIn('-ResX=1920',result);self.assertIn('-ResY=1080',result)
        self.assertEqual(len([x for x in result if x.startswith('-ResX=')]),1)

    def test_rejects_packaged_or_missing_project_command(self):
        for command in (['MetaRescue.exe'],['MetaRescue.exe','/Game/Maps/RescueQuarter']):
            with self.assertRaises(ValueError):film_command(command,Path('runtime'),Path('plan'),Path('capture'),1920,1080)


if __name__=='__main__':unittest.main()
