class IntermediateFormat:
    _version = 0.2
    f"""
    Intermediate Format: v{_version}.
    
    The purpose of the IntermediateFormat class is to describe DSCS model data with a single class.

    The imported data is split across several files, and collating this into a single location makes it more 
    convenient to program against.
    """

    def __init__(self):
        self.skeleton = Skeleton()
        self.meshes = []
        self.materials = []
        self.textures = []
        self.animations = {}
        self.unknown_data = {}
        
    def new_mesh(self):
        md = MeshData()
        self.meshes.append(md)
        return md
        
    def new_material(self):
        md = MaterialData()
        self.materials.append(md)
        return md
        
    def new_texture(self):
        td = TextureData()
        self.textures.append(td)
        return td

    def new_anim(self, key):
        ad = Animation()
        self.animations[key] = ad
        return ad

        
class MeshData:
    def __init__(self):
        self.vertices = []
        self.vertex_groups = []
        self.polygons = []
        self.material_id = None

        self.unknown_data = {}
        
    def add_vertex(self, position=None, normal=None, UV=None, vertex_groups=None, weights=None):
        self.vertices.append(Vertex(position, normal, UV, vertex_groups, weights))

    def add_vertex_group(self, bone_idx, vertex_indices=None, weights=None):
        self.vertex_groups.append(VertexGroup(bone_idx, vertex_indices, weights))
    
    def add_polygon(self, indices):
        self.polygons.append(Polygon(indices))


class Vertex:
    def __init__(self, position, normal, UV, vertex_groups, weights):
        self.position = position
        self.normal = normal
        self.UV = UV
        self.vertex_groups = vertex_groups
        self.vertex_group_weights = weights

        self.unknown_data = {}


class VertexGroup:
    def __init__(self, bone_idx, vertex_indices, weights):
        self.bone_idx = bone_idx
        self.vertex_indices = vertex_indices
        self.weights = weights


class Polygon:
    def __init__(self, indices):
        self.indices = indices


class MaterialData:
    def __init__(self):
        self.name = None
        self.texture_id = None
        self.toon_texture_id = None
        self.rgba = None
        self.specular_coeff = None
        self.shader_hex = None

        self.shader_uniforms = {}
        self.unknown_data = {}


class TextureData:
    def __init__(self):
        self.name = None
        self.filepath = None


class Skeleton:
    def __init__(self):
        self.bone_names = []
        self.inverse_bind_pose_matrices = []
        self.rest_pose = []
        self.rest_pose_delta = []
        self.bone_relations = []

        self.unknown_data = {}


class Animation:
    def __init__(self):
        self.rotations = {}
        self.locations = {}
        self.scales = {}
        self.playback_rate = 24

    def add_rotation_fcurve(self, bone_idx, frames, values):
        self.rotations[bone_idx] = FCurve(frames, values)

    def add_location_fcurve(self, bone_idx, frames, values):
        self.locations[bone_idx] = FCurve(frames, values)

    def add_scale_fcurve(self, bone_idx, frames, values):
        self.scales[bone_idx] = FCurve(frames, values)

    @property
    def num_frames(self):
        rot_frames = [e.frames for e in self.rotations.values()]
        rot_frames = [subitem for item in rot_frames for subitem in item]
        loc_frames = [e.frames for e in self.locations.values()]
        loc_frames = [subitem for item in loc_frames for subitem in item]
        scl_frames = [e.frames for e in self.scales.values()]
        scl_frames = [subitem for item in scl_frames for subitem in item]
        res = (*rot_frames, *loc_frames, *scl_frames)
        if len(res):
            return max(res)
        else:
            return 0


class FCurve:
    def __init__(self, frames, values):
        self.frames = frames
        self.values = values
