"""Read actual imported meshes, PBR references, glass, LODs and sampled bone poses."""
from pathlib import Path
import json
import math

import unreal


root = Path(unreal.Paths.project_dir()).resolve().parents[1]
library = json.loads((root/'unreal/MetaRescue/Content/Scenario/library-v2.json').read_text())
sub = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem) or unreal.new_object(unreal.StaticMeshEditorSubsystem)
lib = unreal.MaterialEditingLibrary
rows = []
for record in library['assets']:
    triangles = 0
    reduced = 0
    for part in record['parts']:
        mesh = unreal.load_asset(part['mesh'])
        assert isinstance(mesh, unreal.StaticMesh), part['mesh']
        triangles += mesh.get_num_triangles(0)
        assert sub.get_num_uv_channels(mesh, 0) > 0, part['mesh']
        assert mesh.get_editor_property('body_setup').get_editor_property('collision_trace_flag') == unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE
        dims = [value*2 for value in mesh.get_bounds().box_extent.to_tuple()]
        assert all(math.isfinite(value) and value >= 0 for value in dims)
        assert all(abs(a-b)<max(2,b*.03) for a,b in zip(sorted(dims), sorted(v*100 for v in part['dimensions_m']))), part['mesh']
        if mesh.get_num_triangles(0)>7000:
            assert sub.get_lod_count(mesh)==4, part['mesh']
            assert mesh.get_num_triangles(0)>mesh.get_num_triangles(3)>0, part['mesh']
            reduced += 1
        for slot in mesh.get_editor_property('static_materials'):
            mat = slot.get_editor_property('material_interface')
            assert mat is not None, part['mesh']
            for expression in lib.get_material_expressions(mat):
                if isinstance(expression, unreal.MaterialExpressionTextureSample):
                    assert expression.get_editor_property('texture') is not None, mat.get_path_name()
            if part['role']=='glass':
                assert mat.get_editor_property('blend_mode')==unreal.BlendMode.BLEND_TRANSLUCENT, mat.get_path_name()
                assert lib.get_material_property_input_node(mat,unreal.MaterialProperty.MP_OPACITY) is not None
    for material in record['materials']:
        if material['glass']:
            path = record['folder']+'/Materials/'+material['name'].replace('.','_')
            mat = unreal.load_asset(path)
            assert mat is not None and mat.get_editor_property('blend_mode')==unreal.BlendMode.BLEND_TRANSLUCENT, path
    rows.append({'id':record['id'],'parts':len(record['parts']),'triangles':triangles,'meshes_with_four_lods':reduced})

# Evaluate actual imported animation data at several phases, not only file names.
rig = json.loads((root/'artifacts/3d-world/ue-mannequin-import.json').read_text())
options = unreal.AnimPoseEvaluationOptions()
options.set_editor_property('optional_skeletal_mesh',unreal.load_asset(rig['skin']))
clips = []
for clip in rig['clips']:
    animation = unreal.load_asset(clip['path'])
    poses = [unreal.AnimPoseExtensions.get_anim_pose_at_time(animation, clip['length_s']*phase, options)
             for phase in [0,.25,.5,.75]]
    assert all(unreal.AnimPoseExtensions.is_valid(pose) for pose in poses), clip['name']
    bones = list(unreal.AnimPoseExtensions.get_bone_names(poses[0]))
    assert len(bones)>=24, clip['name']
    changed = []
    for bone in bones:
        transforms = [unreal.AnimPoseExtensions.get_bone_pose(pose,bone,unreal.AnimPoseSpaces.LOCAL) for pose in poses]
        values = [list(transform.translation.to_tuple())+list(transform.rotation.to_tuple()) for transform in transforms]
        assert all(math.isfinite(value) for row in values for value in row), (clip['name'],str(bone))
        if max(abs(a-b) for row in values[1:] for a,b in zip(values[0],row))>1e-4:changed.append(str(bone))
    assert changed, 'No actual bone movement: '+clip['name']
    if clip['name'] in {'Walking','Running'}:
        assert len(changed)>=8, 'Locomotion lost limb channels: '+clip['name']+' '+str(changed)
    clips.append({'name':clip['name'],'length_s':clip['length_s'],'bones':len(bones),'moving_bones':changed})

water = unreal.load_asset('/Game/Materials/M_QuarterWater')
assert water.get_editor_property('shading_model')==unreal.MaterialShadingModel.MSM_SINGLE_LAYER_WATER
assert sum(isinstance(node,unreal.MaterialExpressionSingleLayerWaterMaterialOutput)
           for node in lib.get_material_expressions(water))==1
for name in ['ElectricalFire','CollapseDust','PipeLeak']:
    assert isinstance(unreal.load_asset('/Game/Effects/NS_'+name),unreal.NiagaraSystem)
result = {'passed':True,'assets':rows,'sampled_imported_animations':clips,'single_layer_water_output_count':1}
(root/'artifacts/3d-world/ue-library-verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
unreal.log('MR_LIBRARY_VERIFIED '+str(len(rows))+' assemblies and '+str(len(clips))+' sampled clips')
