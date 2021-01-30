from ..FileReaders.NameReader import NameReader
from ..FileReaders.SkelReader import SkelReader
from ..FileReaders.GeomReader import GeomReader
from ..FileReaders.AnimReader import AnimReader
from .IntermediateFormat import IntermediateFormat

import itertools
import os
import numpy as np


def generate_intermediate_format_from_files(filepath, platform):
    """
    Opens name, skel, and geom files associated with the given filename and generates an IntermediateFormat object.
    Images are assumed to be in a sub-directory of the given file's directory named 'images'.

    Returns
    ------
    An IntermediateFormat representation of the data.
    """
    with open(filepath + '.name', 'rb') as F:
        imported_namedata = NameReader(F)
        imported_namedata.read()
    with open(filepath + '.skel', 'rb') as F:
        imported_skeldata = SkelReader(F)
        imported_skeldata.read()
    with open(filepath + '.geom', 'rb') as F:
        imported_geomdata = GeomReader.for_platform(F, platform=platform)
        imported_geomdata.read()

    directory = os.path.split(filepath)
    filename = directory[-1]
    directory = os.path.join(*directory[:-1])

    imported_animdata = {}
    for afile in os.listdir(directory):
        afilepath = os.path.join(directory, afile)
            afile_name, afile_ext = os.path.splitext(afile)
            print(afile)
            with open(afilepath, 'rb') as F:
                iar = AnimReader(F, imported_skeldata)
                iar.read()
            imported_animdata[afile_name] = iar

    images_directory = os.path.join(*os.path.split(filepath)[:-1], 'images')

    model_data = IntermediateFormat()
    add_meshes(model_data, imported_geomdata)
    add_materials(model_data, imported_namedata, imported_geomdata, os.path.split(filepath)[-1])
    add_textures(model_data, imported_geomdata, images_directory)
    add_skeleton(model_data, imported_namedata, imported_skeldata, imported_geomdata)
    add_anims(model_data, imported_animdata)

    return model_data


##################################
#  Polygon data type converters  #
##################################
def triangle_strips_to_polys(idxs):
    triangles = []
    for i, tri in enumerate(zip(idxs, idxs[1:], idxs[2:])):
        order = i % 2
        tri = (tri[0 + order], tri[1 - order], tri[2])
        triangle = set(tri)
        if not (len(triangle) != 3 or tri in triangles):
            triangles.append(tri)
    return triangles


def triangles_to_polys(idxs):
    triangles = []
    for tri, (idx_a, idx_b, idx_c) in enumerate(zip(idxs[::3], idxs[1::3], idxs[2::3])):
        triangles.append((idx_a, idx_b, idx_c))
    return triangles


triangle_converters = {'Triangles': triangles_to_polys,
                       'TriangleStrips': triangle_strips_to_polys}


##############################
#  Factory helper functions  #
##############################
def add_meshes(model_data, imported_geomdata):
    for mesh in imported_geomdata.meshes:
        model_data.new_mesh()
        current_IF_mesh = model_data.meshes[-1]
        for bone_id in mesh.weighted_bone_idxs:
            current_IF_mesh.add_vertex_group(bone_id, [], [])
        uk_keys = ['UnknownVertexUsage1', 'UnknownVertexUsage2', 'UV2', 'UnknownVertexUsage4', 'UnknownVertexUsage5']
        for i, vertex in enumerate(mesh.vertex_data):
            pos = vertex.get('Position')
            #if len(pos) > 3:
            #    assert 0
            norm = vertex.get('Normal')
            uv = vertex.get('UV')
            vgroups = vertex.get('WeightedBoneID')
            weights = vertex.get('BoneWeight')

            if uv is not None:
                uv = (uv[0], 1 - uv[-1])
            if 'WeightedBoneID' in vertex:
                for j, (three_x_bone_id, weight) in enumerate(zip(vgroups, weights)):
                    if weight == 0:
                        continue
                    vertex_group_idx = three_x_bone_id // 3
                    vgroups[j] = vertex_group_idx
                    current_IF_mesh.vertex_groups[vertex_group_idx].vertex_indices.append(i)
                    current_IF_mesh.vertex_groups[vertex_group_idx].weights.append(weight)
            elif mesh.max_vertex_groups_per_vertex == 0:
                bone_idx = 0
                vgroups = [bone_idx]
                current_IF_mesh.vertex_groups[bone_idx].vertex_indices.append(i)
                current_IF_mesh.vertex_groups[bone_idx].weights.append(1)
            elif mesh.max_vertex_groups_per_vertex == 1:
                bone_idx = int(pos[3]) // 3
                vgroups = [bone_idx]
                current_IF_mesh.vertex_groups[bone_idx].vertex_indices.append(i)
                current_IF_mesh.vertex_groups[bone_idx].weights.append(1)
            current_IF_mesh.add_vertex(pos[:3], norm, uv, vgroups, weights)
            for key in uk_keys:
                if key in vertex:
                    current_IF_mesh.vertices[-1].unknown_data[key] = vertex[key]

        triangles = triangle_converters[mesh.polygon_data_type](mesh.polygon_data)
        for tri in triangles:
            current_IF_mesh.add_polygon(tri)
        current_IF_mesh.material_id = mesh.material_id

        # Add unknown data
        current_IF_mesh.unknown_data['unknown_0x31'] = mesh.unknown_0x31
        current_IF_mesh.unknown_data['unknown_0x34'] = mesh.unknown_0x34
        current_IF_mesh.unknown_data['unknown_0x36'] = mesh.unknown_0x36
        current_IF_mesh.unknown_data['unknown_0x4C'] = mesh.unknown_0x4C

        # Calculable
        #current_IF_mesh.unknown_data['mesh_centre'] = mesh.mesh_centre
        #current_IF_mesh.unknown_data['bounding_box_lengths'] = mesh.bounding_box_lengths

        model_data.meshes[-1] = current_IF_mesh
    model_data.unknown_data['unknown_cam_data_1'] = imported_geomdata.unknown_cam_data_1
    model_data.unknown_data['unknown_cam_data_2'] = imported_geomdata.unknown_cam_data_2

    model_data.unknown_data['unknown_footer_data'] = imported_geomdata.unknown_footer_data


def add_materials(model_data, imported_namedata, imported_geomdata, filename):
    #assert len(imported_namedata.material_names) == len(imported_geomdata.material_data), \
    #    f"Mismatch between material names and unique material data. {len(imported_namedata.material_names)} {len(imported_geomdata.material_data)}"
    model_data.unknown_data['material names'] = imported_namedata.material_names
    for i, material in enumerate(imported_geomdata.material_data):
        model_data.new_material()
        # I can't figure out how to match up the material names to the materials yet when there are fewer names than materials
        model_data.materials[-1].name = filename + "_mat_{:03d}".format(i)  # str(i)  # model_data.unknown_data['material names'][i]

        # Add unknown data
        model_data.materials[-1].unknown_data['unknown_0x00'] = material.unknown_0x00
        model_data.materials[-1].unknown_data['unknown_0x02'] = material.unknown_0x02
        model_data.materials[-1].shader_hex = material.shader_hex
        # Might be calculable?!
        #  model_data.materials[-1].unknown_data['unknown_0x16'] = material.unknown_0x16

        for i, material_component in enumerate(material.material_components):
            # Appears to mark the block as identifying a texture ID
            if material_component.component_type == 50:
                model_data.materials[-1].texture_id = material_component.data[0]
            elif material_component.component_type == 51:
                model_data.materials[-1].rgba = material_component.data
            elif material_component.component_type == 56:
                model_data.materials[-1].specular_coeff = material_component.data[0]
            elif material_component.component_type == 72:
                model_data.materials[-1].toon_texture_id = material_component.data[0]
            model_data.materials[-1].unknown_data[f'type_1_component_{material_component.component_type}'] = material_component.data

        for i, material_component in enumerate(material.unknown_data):
            model_data.materials[-1].unknown_data[f'type_2_component_{material_component.maybe_component_type}'] = material_component.data


def add_textures(model_data, imported_geomdata, image_folder_path):
    for texture in imported_geomdata.texture_data:
        directory = os.path.join(image_folder_path, texture) + ".img"
        model_data.new_texture()
        model_data.textures[-1].name = texture
        model_data.textures[-1].filepath = directory


def add_skeleton(model_data, imported_namedata, imported_skeldata, imported_geomdata):
    model_data.skeleton.bone_names = imported_namedata.bone_names
    model_data.skeleton.bone_relations = imported_skeldata.parent_bones
    model_data.skeleton.unknown_data['transforms'] = []
    for bone_data in imported_geomdata.bone_data:
        position = (-bone_data.xpos, -bone_data.ypos, -bone_data.zpos)

        transform = np.array([bone_data.x_axis, bone_data.y_axis, bone_data.z_axis])
        position = np.dot(transform.T, np.array(position))

        model_data.skeleton.bone_positions.append(position)
        model_data.skeleton.bone_xaxes.append(bone_data.x_axis)
        model_data.skeleton.bone_yaxes.append(bone_data.y_axis)
        model_data.skeleton.bone_zaxes.append(bone_data.z_axis)
        model_data.skeleton.unknown_data['transforms'].append(transform)


    # Put the unknown data into the skeleton
    model_data.skeleton.unknown_data['unknown_0x0C'] = imported_skeldata.unknown_0x0C
    model_data.skeleton.unknown_data['unknown_parent_child_data'] = imported_skeldata.unknown_parent_child_data
    model_data.skeleton.unknown_data['bone_data'] = imported_skeldata.bone_data
    model_data.skeleton.unknown_data['unknown_data_1'] = imported_skeldata.unknown_data_1
    model_data.skeleton.unknown_data['unknown_data_2'] = imported_skeldata.unknown_data_2
    model_data.skeleton.unknown_data['unknown_data_3'] = imported_skeldata.unknown_data_3
    model_data.skeleton.unknown_data['unknown_data_4'] = imported_skeldata.unknown_data_4


def add_anims(model_data, imported_animdata):
    for key, ar in imported_animdata.items():
        ad = model_data.new_anim(key)

        rotation_fcurves_frames = {bone_idx: [] for bone_idx in range(ar.num_bones)}
        rotation_fcurves_values = {bone_idx: [] for bone_idx in range(ar.num_bones)}
        location_fcurves_frames = {bone_idx: [] for bone_idx in range(ar.num_bones)}
        location_fcurves_values = {bone_idx: [] for bone_idx in range(ar.num_bones)}
        scale_fcurves_frames = {bone_idx: [] for bone_idx in range(ar.num_bones)}
        scale_fcurves_values = {bone_idx: [] for bone_idx in range(ar.num_bones)}

        # First add in the rotations, locations, and scales that are constant throughout the animation
        for bone_idx, value in zip(ar.initial_pose_rotations_bone_idxs, ar.initial_pose_bone_rotations):
            rotation_fcurves_frames[bone_idx].append(0)
            rotation_fcurves_values[bone_idx].append(value)
        for bone_idx, value in zip(ar.initial_pose_locations_bone_idxs, ar.initial_pose_bone_locations):
            location_fcurves_frames[bone_idx].append(0)
            location_fcurves_values[bone_idx].append(value)
        for bone_idx, value in zip(ar.initial_pose_scales_bone_idxs, ar.initial_pose_bone_scales):
            scale_fcurves_frames[bone_idx].append(0)
            scale_fcurves_values[bone_idx].append(value)

        for (cumulative_frames, nframes), substructure in zip(ar.keyframe_counts, ar.unknown_data_8[:-1]):

            for bone_idx, value in zip(ar.keyframe_rotations_bone_idxs, substructure.unknown_data_1):
                rotation_fcurves_frames[bone_idx].append(cumulative_frames)
                rotation_fcurves_values[bone_idx].append(value)
            for bone_idx, value in zip(ar.keyframe_locations_bone_idxs, substructure.unknown_data_2):
                location_fcurves_frames[bone_idx].append(cumulative_frames)
                location_fcurves_values[bone_idx].append(value)
            for bone_idx, value in zip(ar.keyframe_scales_bone_idxs, substructure.unknown_data_3):
                scale_fcurves_frames[bone_idx].append(cumulative_frames)
                scale_fcurves_values[bone_idx].append(value)

            if nframes != 0:
                masks = chunks(substructure.unknown_data_5, nframes)
            else:
                masks = []
            rotations = iter(substructure.unknown_data_6)
            locations = iter(substructure.unknown_data_7)
            scales = iter(substructure.unknown_data_8)

            for bone_idx, mask in zip(ar.keyframe_rotations_bone_idxs, masks):
                frames = [j+cumulative_frames+1 for j, elem in enumerate(mask) if elem == '1']
                values = itertools.islice(rotations, len(frames))  # Pop the next num_frames rotations
                rotation_fcurves_frames[bone_idx].extend(frames)
                rotation_fcurves_values[bone_idx].extend(values)
            for bone_idx, mask in zip(ar.keyframe_locations_bone_idxs, masks):
                frames = [j+cumulative_frames+1 for j, elem in enumerate(mask) if elem == '1']
                values = itertools.islice(locations, len(frames)) # Pop the next num_frames locations
                location_fcurves_frames[bone_idx].extend(frames)
                location_fcurves_values[bone_idx].extend(values)
            for bone_idx, mask in zip(ar.keyframe_scales_bone_idxs, masks):
                frames = [j+cumulative_frames+1 for j, elem in enumerate(mask) if elem == '1']
                values = itertools.islice(scales, len(frames))  # Pop the next num_frames scales
                scale_fcurves_frames[bone_idx].extend(frames)
                scale_fcurves_values[bone_idx].extend(values)

        for bone_idx in range(ar.num_bones):
            ad.add_rotation_fcurve(bone_idx, rotation_fcurves_frames[bone_idx], rotation_fcurves_values[bone_idx])
            ad.add_location_fcurve(bone_idx, location_fcurves_frames[bone_idx], location_fcurves_values[bone_idx])
            ad.add_scale_fcurve(bone_idx, scale_fcurves_frames[bone_idx], scale_fcurves_values[bone_idx])


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]
