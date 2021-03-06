import bpy
import numpy as np
import os
import shutil
from bpy.props import BoolProperty
from bpy_extras.io_utils import ImportHelper
from bpy_extras.image_utils import load_image
from bpy_extras.object_utils import object_data_add
from mathutils import Vector, Matrix
from ..CollatedData.FromReadWrites import generate_intermediate_format_from_files
from ..FileReaders.GeomReader.ShaderUniforms import shader_textures


def set_new_rest_pose(armature_name, bone_names, rest_pose_delta):
    """
    This function implements the instructions of this [1] exceptionally useful blog post in Python script form.
    The steps of this blog post are pointed out in the code with comments.
    It takes an armature with a given rest pose and deforms the meshes attached to that armature such that a pose
    becomes a new rest pose. It should be relatively general.

    [1] https://nixart.wordpress.com/2013/03/28/modifying-the-rest-pose-in-blender/
    """
    # 1) Select your armature and go in “Pose Mode”.
    model_armature = bpy.data.objects[armature_name]
    bpy.context.view_layer.objects.active = model_armature
    bpy.ops.object.mode_set(mode="POSE")

    # 2) Pose your object in your new rest pose.
    for i, (bone_name, (rest_quat, rest_pos, rest_scl)) in enumerate(zip(bone_names, rest_pose_delta)):
        model_armature.pose.bones[bone_name].rotation_quaternion = np.roll(rest_quat, 1)
        model_armature.pose.bones[bone_name].location = rest_pos
        model_armature.pose.bones[bone_name].scale = rest_scl

    # 3) Go in “Object Mode” and select your deformed object.
    bpy.ops.object.mode_set(mode="OBJECT")
    for ob in model_armature.children:
        bpy.context.view_layer.objects.active = ob
        # 4) In the object’s “Object Modifiers” stack, copy the “Armature Modifier” by pressing the “Copy” button. You should have two “Armature Modifiers”, one above the other in the stack, with the same parameters. This will deform your object twice, but it is ok. If you go in “Edit Mode”, you will see that the mesh has been deformed in your new rest pose.
        first_armature_modifier = [m for m in ob.modifiers if m.type == 'ARMATURE'][0]
        bpy.ops.object.modifier_copy(modifier=first_armature_modifier.name)
        # 5) Apply the first “Armature Modifier” (the top one), but keep the bottom one. The latter will replace the old “Armature Modifier” and will allow to pose your object with respect to your new rest pose. At this point, the object will still be deformed twice. That is because we need to apply the current pose as the new rest pose.
        bpy.ops.object.modifier_apply(modifier=first_armature_modifier.name)
    # 6) Select your armature and go in “Pose Mode”.
    bpy.context.view_layer.objects.active = model_armature
    bpy.ops.object.mode_set(mode="POSE")
    # 7) “Apply Pose as Rest Pose” in the “Pose” menu. This will clear the double deformation and put your object in your new rest pose.
    bpy.ops.pose.armature_apply()


class ImportDSCSBase:
    bl_label = 'Digimon Story: Cyber Sleuth (.name, .skel, .geom)'
    bl_options = {'REGISTER', 'UNDO'}
    # This will actually work with any file extension since the code just looks for the right ones...
    filename_ext = "*.name"

    filter_glob: bpy.props.StringProperty(
                                             default="*.name",
                                             options={'HIDDEN'},
                                         )

    import_anims: BoolProperty(
        name="Import Animations",
        description="Enable/disable to import/not import animations.",
        default=True)
    import_pose_mesh: BoolProperty(
        name="Import Alternative Skeleton",
        description="Enable/disable to import/not import the second skeleton.",
        default=False)
    do_import_boundboxes: BoolProperty(
        name="Import Bounding Boxes",
        description="Enable/disable to import/not import bounding boxes.",
        default=False)

    def import_file(self, context, filepath, platform):
        bpy.ops.object.select_all(action='DESELECT')
        model_data = generate_intermediate_format_from_files(filepath, platform, self.import_anims)
        filename = os.path.split(filepath)[-1]
        parent_obj = bpy.data.objects.new(filename, None)

        bpy.context.collection.objects.link(parent_obj)
        armature_name = f'{filename}_armature'
        self.import_skeleton(parent_obj, filename, model_data, armature_name)
        if self.import_pose_mesh:
            self.import_rest_pose_skeleton(parent_obj, filename, model_data, armature_name+"_2")
        if self.do_import_boundboxes:
            use_arm_name = armature_name
            if self.import_pose_mesh:
                use_arm_name += "_2"
            self.import_boundboxes(model_data, filename, use_arm_name)
        self.import_materials(model_data)
        self.import_meshes(parent_obj, filename, model_data, armature_name)
        # set_new_rest_pose(armature_name, model_data.skeleton.bone_names, model_data.skeleton.rest_pose_delta)
        self.import_animations(armature_name, model_data)

        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.view_layer.objects.active = parent_obj

        # Rotate to the Blender coordinate convention
        parent_obj.rotation_euler = (np.pi / 2, 0, 0)
        parent_obj.select_set(True)
        bpy.ops.object.transform_apply(rotation=True)
        parent_obj.select_set(False)

    def import_rest_pose_skeleton(self, parent_obj, filename, model_data, armature_name):
        model_armature = bpy.data.objects.new(armature_name, bpy.data.armatures.new(f'{filename}_armature_data'))
        bpy.context.collection.objects.link(model_armature)
        model_armature.parent = parent_obj

        # Rig
        list_of_bones = {}

        bpy.context.view_layer.objects.active = model_armature
        bpy.ops.object.mode_set(mode='EDIT')

        bone_matrices = model_data.skeleton.rest_pose
        for i, relation in enumerate(model_data.skeleton.bone_relations):
            child, parent = relation
            child_name = model_data.skeleton.bone_names[child]
            if child_name in list_of_bones:
                continue

            bone_matrix = bone_matrices[i]
            #pos = bone_matrix[:, 3][:3]

            #####

            #child_pos = pos

            bone = model_armature.data.edit_bones.new(child_name)

            list_of_bones[child_name] = bone
            bone.head = np.array([0., 0., 0.])
            bone.tail = np.array([0., 0.2, 0.])  # Make this scale with the model size in the future, for convenience
            bone.transform(Matrix(bone_matrix.tolist()))

            #bone.head = np.array([0., 0., 0.]) + child_pos
            #bone.tail = np.array(bone.tail) + child_pos

            if parent != -1:
                bone.parent = list_of_bones[model_data.skeleton.bone_names[parent]]

        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.context.view_layer.objects.active = parent_obj

    def import_skeleton(self, parent_obj, filename, model_data, armature_name):
        model_armature = bpy.data.objects.new(armature_name, bpy.data.armatures.new(f'{filename}_armature_data'))
        bpy.context.collection.objects.link(model_armature)
        model_armature.parent = parent_obj

        # Rig
        list_of_bones = {}

        bpy.context.view_layer.objects.active = model_armature
        bpy.ops.object.mode_set(mode='EDIT')

        bone_matrices = model_data.skeleton.inverse_bind_pose_matrices
        for i, relation in enumerate(model_data.skeleton.bone_relations):
            child, parent = relation
            child_name = model_data.skeleton.bone_names[child]
            if child_name in list_of_bones:
                continue

            bm = bone_matrices[child]
            # This should just be the inverse though?!
            pos = bm[:3, 3]
            pos *= -1  # For some reason, need to multiply the positions by -1?

            rotation = bm[:3, :3]
            pos = np.dot(rotation.T, pos)  # And then rotate them?!

            bone_matrix = np.zeros((4, 4))
            bone_matrix[3, :3] = pos
            bone_matrix[:3, :3] = rotation.T
            bone_matrix[3, 3] = 1

            #bone_matrix = np.linalg.inv(bm)

            #####

            child_pos = pos

            bone = model_armature.data.edit_bones.new(child_name)

            list_of_bones[child_name] = bone
            bone.head = np.array([0., 0., 0.])
            bone.tail = np.array([0., 0.2, 0.])  # Make this scale with the model size in the future, for convenience
            bone.transform(Matrix(bone_matrix.tolist()))

            bone.head = np.array([0., 0., 0.]) + child_pos
            bone.tail = np.array(bone.tail) + child_pos

            if parent != -1:
                bone.parent = list_of_bones[model_data.skeleton.bone_names[parent]]

        # Add the unknown data
        model_armature['unknown_0x0C'] = model_data.skeleton.unknown_data['unknown_0x0C']
        model_armature['unknown_data_1'] = model_data.skeleton.unknown_data['unknown_data_1']
        model_armature['unknown_data_2'] = model_data.skeleton.unknown_data['unknown_data_2']
        model_armature['unknown_data_3'] = model_data.skeleton.unknown_data['unknown_data_3']
        model_armature['unknown_data_4'] = model_data.skeleton.unknown_data['unknown_data_4']

        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.context.view_layer.objects.active = parent_obj

    def import_materials(self, model_data):
        for i, IF_material in enumerate(model_data.materials):
            new_material = bpy.data.materials.new(name=IF_material.name)
            # Unknown data
            new_material['unknown_0x00'] = IF_material.unknown_data['unknown_0x00']
            new_material['unknown_0x02'] = IF_material.unknown_data['unknown_0x02']
            new_material['shader_hex'] = IF_material.shader_hex
            new_material['unknown_0x16'] = IF_material.unknown_data['unknown_0x16']

            for nm, value in IF_material.shader_uniforms.items():
                new_material[nm] = value
            for nm, value in IF_material.unknown_data['unknown_material_components'].items():
                new_material[str(nm)] = value

            new_material.use_nodes = True

            # Set some convenience variables
            shader_uniforms = IF_material.shader_uniforms
            nodes = new_material.node_tree.nodes
            connect = new_material.node_tree.links.new

            # Remove the default shader node
            bsdf_node = nodes.get('Principled BSDF')
            nodes.remove(bsdf_node)

            output_node = new_material.node_tree.nodes.get('Material Output')
            new_material.node_tree.links.clear()
            self.import_material_texture_nodes(nodes, model_data, IF_material.shader_uniforms)

            final_diffuse_node = None
            if 'DiffuseTextureID' in shader_uniforms:
                tex0_img_node = nodes["DiffuseTextureID"]
                tex0_node = nodes.new('ShaderNodeBsdfPrincipled')
                tex0_node.name = "DiffuseShader"
                tex0_node.label = "DiffuseShader"

                # Might be updated by following nodes
                final_diffuse_colour_node = tex0_img_node
                final_alpha_node = tex0_img_node
                if "ToonTextureID" in shader_uniforms:
                    toon_texture_node = nodes["ToonTextureID"]
                    toon_node = nodes.new('ShaderNodeBsdfToon')
                    toon_node.name = "ToonShader"
                    toon_node.label = "ToonShader"
                    connect(toon_texture_node.outputs['Color'], toon_node.inputs['Color'])

                    converter_node = nodes.new('ShaderNodeShaderToRGB')
                    connect(toon_node.outputs['BSDF'], converter_node.inputs['Shader'])

                    mix_node = new_material.node_tree.nodes.new('ShaderNodeMixRGB')
                    mix_node.blend_type = 'MULTIPLY'

                    connect(final_diffuse_colour_node.outputs['Color'], mix_node.inputs['Color1'])
                    connect(converter_node.outputs['Color'], mix_node.inputs['Color2'])

                    final_diffuse_colour_node = mix_node
                if "DiffuseColour" in shader_uniforms:
                    rgba_node = nodes.new('ShaderNodeRGB')
                    rgba_node.name = "DiffuseColour"
                    rgba_node.label = "DiffuseColour"
                    rgba_node.outputs['Color'].default_value = shader_uniforms["DiffuseColour"]

                    mix_node = nodes.new('ShaderNodeMixRGB')
                    mix_node.blend_type = 'MULTIPLY'
                    connect(final_diffuse_colour_node.outputs['Color'], mix_node.inputs['Color1'])
                    connect(rgba_node.outputs['Color'], mix_node.inputs['Color2'])

                    final_diffuse_colour_node = mix_node

                # Vertex Colours
                vertex_colour_input_node = nodes.new('ShaderNodeVertexColor')
                vertex_colour_input_node.name = "VertexColour"
                vertex_colour_input_node.label = "VertexColour"

                mix_node = nodes.new('ShaderNodeMixRGB')
                mix_node.blend_type = 'MULTIPLY'
                connect(final_diffuse_colour_node.outputs['Color'], mix_node.inputs['Color1'])
                connect(vertex_colour_input_node.outputs['Color'], mix_node.inputs['Color2'])
                final_diffuse_colour_node = mix_node

                alpha_mix_node = nodes.new('ShaderNodeMath')
                alpha_mix_node.operation = "MULTIPLY"
                connect(final_alpha_node.outputs['Alpha'], alpha_mix_node.inputs[0])
                connect(vertex_colour_input_node.outputs['Alpha'], alpha_mix_node.inputs[1])
                final_alpha_node = alpha_mix_node
                connect(final_alpha_node.outputs['Value'], tex0_node.inputs['Alpha'])

                if "SpecularStrength" in shader_uniforms:
                    specular_value = nodes.new('ShaderNodeValue')
                    specular_value.name = 'SpecularStrength'
                    specular_value.label = 'SpecularStrength'
                    specular_value.outputs['Value'].default_value = shader_uniforms["SpecularStrength"][0]
                    connect(specular_value.outputs['Value'], tex0_node.inputs['Specular'])
                connect(final_diffuse_colour_node.outputs['Color'], tex0_node.inputs['Base Color'])
                final_diffuse_node = tex0_node

            elif "DiffuseColour" in shader_uniforms:
                rgba_node = nodes.new('ShaderNodeRGB')
                rgba_node.name = "DiffuseColour"
                rgba_node.label = "DiffuseColour"
                rgba_node.outputs['Color'].default_value = shader_uniforms["DiffuseColour"]

                diffuse_node = nodes.new('ShaderNodeBsdfDiffuse')
                diffuse_node.name = "DiffuseColourShader"
                diffuse_node.label = "DiffuseColourShader"

                connect(rgba_node.outputs['Color'], diffuse_node.inputs['Color'])
                final_diffuse_node = diffuse_node

            if final_diffuse_node is not None:
                connect(final_diffuse_node.outputs['BSDF'], output_node.inputs['Surface'])

            new_material.use_backface_culling = True
            new_material.blend_method = 'CLIP'
            new_material.alpha_threshold = 0.7

    def import_material_texture_nodes(self, nodes, model_data, mat_shader_uniforms):
        imported_textures = {}
        for nm in shader_textures.keys():
            if nm in mat_shader_uniforms:
                tex_img_node = nodes.new('ShaderNodeTexImage')
                tex_img_node.name = nm
                tex_img_node.label = nm
                set_texture_node_image(tex_img_node, mat_shader_uniforms[nm][0], model_data.textures[mat_shader_uniforms[nm][0]], imported_textures)

    def build_loops_and_verts(self, model_vertices, model_polygons):
        # Currently unused because it doesn't distinguish overlapping polygons with the same vertices but different vertex orders
        set_compliant_model_vertex_positions = [tuple(vert['Position']) for vert in model_vertices]
        verts = set(set_compliant_model_vertex_positions)
        verts = list(verts)

        map_of_model_verts_to_verts = {i: verts.index(vert) for i, vert in
                                       enumerate(set_compliant_model_vertex_positions)}

        map_of_loops_to_model_vertices = {}
        polys = []
        for poly_idx, poly in enumerate(model_polygons):
            poly_verts = []
            for model_vertex_idx in poly.indices:
                vert_idx = map_of_model_verts_to_verts[model_vertex_idx]
                map_of_loops_to_model_vertices[(poly_idx, vert_idx)] = model_vertex_idx
                poly_verts.append(vert_idx)
            polys.append(poly_verts)

        return verts, polys, map_of_loops_to_model_vertices, map_of_model_verts_to_verts

    def import_boundboxes(self, model_data, filename, armature_name):
        bbox_material = bpy.data.materials.new(name='bbox_material')
        bbox_material.use_backface_culling = True
        bbox_material.blend_method = 'BLEND'
        bbox_material.use_nodes = True
        bsdf_node = bbox_material.node_tree.nodes.get('Principled BSDF')
        bsdf_node.inputs['Alpha'].default_value = 0.2
        for i, IF_mesh in enumerate(model_data.meshes):
            bbox_name = f"{filename}_{i}_boundingbox"
            bbox_mesh = bpy.data.meshes.new(name=bbox_name)
            bbox_mesh_object = bpy.data.objects.new(bbox_name, bbox_mesh)
            mults = [np.array([1., 1., 1.]),
                     np.array([1., 1., -1.]),
                     np.array([1., -1., -1.]),
                     np.array([1., -1., 1.]),
                     np.array([-1., 1., 1.]),
                     np.array([-1., 1., -1.]),
                     np.array([-1., -1., -1.]),
                     np.array([-1., -1., 1.])]

            bbox_verts = [Vector(np.array(IF_mesh.unknown_data['bbc']) + np.array(IF_mesh.unknown_data['bb'])*mult) for mult in mults]

            bbox_faces = [(0, 1, 2, 3), (4, 5, 6, 7),
                          (0, 1, 5, 4), (2, 3, 7, 6),
                          (3, 0, 4, 7), (1, 2, 6, 5)]

            bbox_mesh_object.data.from_pydata(bbox_verts, [], bbox_faces)
            bpy.context.collection.objects.link(bbox_mesh_object)
            bpy.data.objects[bbox_name].active_material = bpy.data.materials['bbox_material']

            bpy.data.objects[bbox_name].select_set(True)
            bpy.data.objects[armature_name].select_set(True)
            bpy.context.view_layer.objects.active = bpy.data.objects[armature_name]
            bpy.ops.object.parent_set(type='ARMATURE')

            bbox_mesh.validate(verbose=True)
            bbox_mesh.update()

            bpy.data.objects[bbox_name].select_set(False)
            bpy.data.objects[armature_name].select_set(False)

    def import_meshes(self, parent_obj, filename, model_data, armature_name):

        for i, IF_mesh in enumerate(model_data.meshes):
            # This function should be the best way to remove duplicate vertices (?) but doesn't pick up overlapping polygons with opposite normals
            # verts, faces, map_of_loops_to_model_vertices, map_of_model_verts_to_verts = self.build_loops_and_verts(IF_mesh.vertices, IF_mesh.polygons)
            # verts = [Vector(vert) for vert in verts]
            edges = []

            # Init mesh
            meshobj_name = f"{filename}_{i}"
            mesh = bpy.data.meshes.new(name=meshobj_name)
            mesh_object = bpy.data.objects.new(meshobj_name, mesh)

            verts = [Vector(v['Position']) for v in IF_mesh.vertices]
            faces = [poly.indices for poly in IF_mesh.polygons]
            mesh_object.data.from_pydata(verts, edges, faces)
            bpy.context.collection.objects.link(mesh_object)


            # Get the loop data
            # map_of_blenderloops_to_modelloops = {}
            # for poly_idx, poly in enumerate(mesh.polygons):
            #     for loop_idx in poly.loop_indices:
            #         vert_idx = mesh.loops[loop_idx].vertex_index
            #         model_vertex = map_of_loops_to_model_vertices[(poly_idx, vert_idx)]
            #         map_of_blenderloops_to_modelloops[loop_idx] = IF_mesh.vertices[model_vertex]

            # Assign normals
            # if 'Normal' in map_of_blenderloops_to_modelloops[0]:
            if 'Normal' in IF_mesh.vertices[0]:
                # loop_normals = [Vector(loop_data['Normal']) for loop_data in map_of_blenderloops_to_modelloops.values()]
                # loop_normals = [Vector(IF_mesh.vertices[loop.vertex_index]['Normal']) for loop in mesh_object.data.loops]
                # mesh_object.data.normals_split_custom_set([(0, 0, 0) for _ in mesh_object.data.loops])
                # mesh_object.data.normals_split_custom_set(loop_normals)
                mesh_object.data.normals_split_custom_set_from_vertices([Vector(v['Normal']) for v in IF_mesh.vertices])

            mesh.use_auto_smooth = True

            # Assign materials
            material_name = model_data.materials[IF_mesh.material_id].name
            active_material = bpy.data.materials[material_name]
            bpy.data.objects[meshobj_name].active_material = active_material

            # Assign UVs
            for uv_type in ['UV', 'UV2', 'UV3']:
                # if uv_type in map_of_blenderloops_to_modelloops[0]:
                if uv_type in IF_mesh.vertices[0]:
                    uv_layer = mesh.uv_layers.new(name=f"{uv_type}Map", do_init=True)
                    for loop_idx, loop in enumerate(mesh.loops):
                        # uv_layer.data[loop_idx].uv = map_of_blenderloops_to_modelloops[loop_idx][uv_type]
                        uv_layer.data[loop_idx].uv = IF_mesh.vertices[loop.vertex_index][uv_type]

            # Assign vertex colours
            if 'Colour' in IF_mesh.vertices[0]:
                colour_map = mesh.vertex_colors.new(name=f"Map", do_init=True)
                for loop_idx, loop in enumerate(mesh.loops):
                    colour_map.data[loop_idx].color = IF_mesh.vertices[loop.vertex_index]['Colour']

            # Rig the vertices
            for IF_vertex_group in IF_mesh.vertex_groups:
                vertex_group = mesh_object.vertex_groups.new(name=model_data.skeleton.bone_names[IF_vertex_group.bone_idx])
                for vert_idx, vert_weight in zip(IF_vertex_group.vertex_indices, IF_vertex_group.weights):
                    #vertex_group.add([map_of_model_verts_to_verts[vert_idx]], vert_weight, 'REPLACE')
                    vertex_group.add([vert_idx], vert_weight, 'REPLACE')

            # Add unknown data
            mesh_object['unknown_0x31'] = IF_mesh.unknown_data['unknown_0x31']
            mesh_object['unknown_0x34'] = IF_mesh.unknown_data['unknown_0x34']
            mesh_object['unknown_0x36'] = IF_mesh.unknown_data['unknown_0x36']
            mesh_object['unknown_0x4C'] = IF_mesh.unknown_data['unknown_0x4C']

            bpy.data.objects[meshobj_name].select_set(True)
            bpy.data.objects[armature_name].select_set(True)
            # I would prefer to do this by directly calling object methods if possible
            # mesh_object.parent_set()...
            bpy.context.view_layer.objects.active = bpy.data.objects[armature_name]
            bpy.ops.object.parent_set(type='ARMATURE')

            mesh.validate(verbose=True)
            mesh.update()

            bpy.data.objects[meshobj_name].select_set(False)
            bpy.data.objects[armature_name].select_set(False)

        # Top-level unknown data
        parent_obj['unknown_cam_data_1'] = model_data.unknown_data['unknown_cam_data_1']
        parent_obj['unknown_cam_data_2'] = model_data.unknown_data['unknown_cam_data_2']
        parent_obj['unknown_footer_data'] = model_data.unknown_data['unknown_footer_data']

    def import_animations(self, armature_name, model_data):
        model_armature = bpy.data.objects[armature_name]
        bpy.context.view_layer.objects.active = model_armature
        bpy.ops.object.mode_set(mode="POSE")

        model_armature.animation_data_create()
        for animation_name, animation_data in list(model_data.animations.items())[::-1]:
            action = bpy.data.actions.new(animation_name)

            for rotation_data, location_data, scale_data, bone_name in zip(animation_data.rotations.values(),
                                                                           animation_data.locations.values(),
                                                                           animation_data.scales.values(),
                                                                           model_data.skeleton.bone_names):
                if len(rotation_data.frames) != 0:
                    for i in range(4):
                        fc = action.fcurves.new(f'pose.bones["{bone_name}"].rotation_quaternion', index=i)
                        fc.keyframe_points.add(count=len(rotation_data.frames))
                        fc.keyframe_points.foreach_set("co", [x for co in zip([float(elem) for elem in rotation_data.frames],
                                                                              [elem[i] for elem in rotation_data.values]) for x in co])
                        fc.update()
                if len(location_data.frames) != 0:
                    for i in range(3):
                        fc = action.fcurves.new(f'pose.bones["{bone_name}"].location', index=i)
                        fc.keyframe_points.add(count=len(location_data.frames))
                        fc.keyframe_points.foreach_set("co", [x for co in zip([float(elem) for elem in location_data.frames],
                                                                              [elem[i] for elem in location_data.values]) for x in co])
                        fc.update()
                if len(scale_data.frames) != 0:
                    for i in range(3):
                        fc = action.fcurves.new(f'pose.bones["{bone_name}"].scale', index=i)
                        fc.keyframe_points.add(count=len(scale_data.frames))
                        fc.keyframe_points.foreach_set("co", [x for co in zip([float(elem) for elem in scale_data.frames],
                                                                              [elem[i] for elem in scale_data.values]) for x in co])
                        fc.update()

            model_armature.animation_data.action = action
            track = model_armature.animation_data.nla_tracks.new()
            track.name = action.name
            track.mute = True
            nla_strip = track.strips.new(action.name, action.frame_range[0], action)
            nla_strip.scale = 24 / animation_data.playback_rate
            model_armature.animation_data.action = None

    def execute_func(self, context, filepath, platform):
        filepath, file_extension = os.path.splitext(filepath)
        assert any([file_extension == ext for ext in
                    ('.name', '.skel', '.geom')]), f"Extension is {file_extension}: Not a name, skel or geom file!"
        self.import_file(context, filepath, platform)

        return {'FINISHED'}


def set_texture_node_image(node, texture_idx, IF_texture, import_memory):
    tex_filename = os.path.split(IF_texture.filepath)[-1]
    tempdir = bpy.app.tempdir
    dds_loc = os.path.join(tempdir, tex_filename)
    if texture_idx not in import_memory:
        import_memory[texture_idx] = tex_filename
        shutil.copy2(IF_texture.filepath, dds_loc)
        bpy.data.images.load(dds_loc)
    node.image = bpy.data.images[tex_filename]


class ImportDSCSPC(ImportDSCSBase, bpy.types.Operator, ImportHelper):
    bl_idname = 'import_file.import_dscs_pc'

    def execute(self, context):
        return super().execute_func(context, self.filepath, 'PC')


class ImportDSCSPS4(ImportDSCSBase, bpy.types.Operator, ImportHelper):
    bl_idname = 'import_file.import_dscs_ps4'

    def execute(self, context):
        return super().execute_func(context, self.filepath, 'PS4')
