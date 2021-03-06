from .BaseRW import BaseRW
import numpy as np


class SkelReader(BaseRW):
    """
    A class to read skel files. These files are split into eight main sections:
        1. The header, which gives file pointers to split the file into its major sections, plus counts of what appears
           in each section.
        2. Pairs of bone indices that seem to have something to do with parent-child relationships, 8 int16s per element
        3. A section of 12 floats per bone
        4. A section of 1 int16 per bone that gives the parent of each bone
        5. A section of one-multiple-of-8 per unknown_0x0C
        6. A section of 4 bytes per bone
        7. A section of 1 (u?)int32 per unknown_0x0C
        8. A section of 4 bytes per unknown_0x0C

    Completion status
    ------
    (o) SkelReader can successfully parse all name files in DSDB archive within current constraints.
    (x) SkelReader cannot yet fully interpret all data in name files in DSDB archive.
    (o) SkelReader can write data to skel files.

    Current hypotheses and observations
    ------
    1. There may be a section containing IK data.
    2. There may be a section containing bone constraints.
    3. The above two may instead be in the anim file, if they exist at all
    """
    def __init__(self, io_stream):
        super().__init__(io_stream)

        # Variables that appear in the file header
        self.filetype = None
        self.total_bytes = None
        self.remaining_bytes_after_parent_bones_chunk = None
        self.num_bones = None
        self.unknown_0x0C = None
        self.num_bone_hierarchy_data_lines = None

        self.rel_ptr_to_end_of_bone_hierarchy_data = None
        self.rel_ptr_to_end_of_bone_defs = None
        self.rel_ptr_to_end_of_parent_bones_chunk = None
        self.unknown_rel_ptr_2 = None
        self.unknown_rel_ptr_3 = None
        self.rel_ptr_to_end_of_parent_bones = None

        self.padding_0x26 = None
        self.padding_0x2A = None
        self.padding_0x2E = None
        self.padding_0x32 = None

        # These hold the data stored within the file
        self.bone_hierarchy_data = None
        self.bone_data = None
        self.parent_bones = None
        self.unknown_data_1 = None
        self.unknown_data_2 = None
        self.unknown_data_3 = None
        self.unknown_data_4 = None

        # Utility variables
        self.filesize = None

        self.abs_ptr_bone_hierarchy_data = None
        self.abs_ptr_bone_defs = None
        self.abs_ptr_parent_bones = None
        self.abs_ptr_end_of_parent_bones_chunk = None
        self.abs_ptr_unknown_2 = None
        self.abs_ptr_unknown_3 = None
        self.abs_ptr_unknown_4 = None

    def read(self):
        self.read_write(self.read_buffer, self.read_ascii, self.read_raw, self.cleanup_ragged_chunk_read)
        self.interpret_skel_data()

    def write(self):
        self.reinterpret_skel_data()
        self.read_write(self.write_buffer, self.write_ascii, self.write_raw, self.cleanup_ragged_chunk_write)

    def read_write(self, rw_operator, rw_operator_ascii, rw_operator_raw, chunk_cleanup):
        self.rw_header(rw_operator, rw_operator_ascii)
        self.rw_bone_hierarchy(rw_operator)
        self.rw_bone_data(rw_operator)
        self.rw_parent_bones(rw_operator)
        self.rw_unknown_data_1(rw_operator)
        chunk_cleanup(self.bytestream.tell(), 16)
        self.rw_unknown_data_2(rw_operator)
        self.rw_unknown_data_3(rw_operator)
        self.rw_unknown_data_4(rw_operator)
        chunk_cleanup(self.bytestream.tell() - self.remaining_bytes_after_parent_bones_chunk, 16)

    def rw_header(self, rw_operator, rw_operator_ascii):
        self.assert_file_pointer_now_at(0)

        rw_operator_ascii('filetype', 4)
        self.assert_equal("filetype", "20SE")
        rw_operator('total_bytes', 'Q')
        rw_operator('remaining_bytes_after_parent_bones_chunk', 'I')
        rw_operator('num_bones',  'H')
        rw_operator('unknown_0x0C', 'H')
        rw_operator('num_bone_hierarchy_data_lines', 'I')

        upcd_pos = self.bytestream.tell()  # 24
        rw_operator('rel_ptr_to_end_of_bone_hierarchy_data', 'I')
        bonedefs_pos = self.bytestream.tell()  # 28
        rw_operator('rel_ptr_to_end_of_bone_defs', 'I')
        pb_chunk_ptr_pos = self.bytestream.tell()  # 32
        rw_operator('rel_ptr_to_end_of_parent_bones_chunk', 'I')
        unk2_pos = self.bytestream.tell()  # 36
        rw_operator('unknown_rel_ptr_2', 'I')
        unk3_pos = self.bytestream.tell()  # 40
        rw_operator('unknown_rel_ptr_3', 'I')
        pcp_pos = self.bytestream.tell()  # 44
        rw_operator('rel_ptr_to_end_of_parent_bones', 'I')

        rw_operator('padding_0x26', 'I')
        self.assert_is_zero("padding_0x26")
        rw_operator('padding_0x2A', 'I')
        self.assert_is_zero("padding_0x2A")
        rw_operator('padding_0x2E', 'I')
        self.assert_is_zero("padding_0x2E")
        rw_operator('padding_0x32', 'I')
        self.assert_is_zero("padding_0x32")

        self.abs_ptr_bone_hierarchy_data = upcd_pos + self.rel_ptr_to_end_of_bone_hierarchy_data - (self.num_bone_hierarchy_data_lines * 16)
        self.abs_ptr_bone_defs = bonedefs_pos + self.rel_ptr_to_end_of_bone_defs - (self.num_bones * 12 * 4)
        self.abs_ptr_parent_bones = pcp_pos + self.rel_ptr_to_end_of_parent_bones - self.num_bones * 2
        self.abs_ptr_end_of_parent_bones_chunk = pb_chunk_ptr_pos + self.rel_ptr_to_end_of_parent_bones_chunk
        self.abs_ptr_unknown_2 = unk2_pos + self.unknown_rel_ptr_2 - self.num_bones * 4
        self.abs_ptr_unknown_3 = unk3_pos + self.unknown_rel_ptr_3 - self.unknown_0x0C * 4

        self.assert_equal("total_bytes", self.abs_ptr_unknown_2 + self.remaining_bytes_after_parent_bones_chunk)

    def rw_bone_hierarchy(self, rw_operator):
        # Seems to contain the same info as the parent_bones with repeats and bugs..?
        self.assert_file_pointer_now_at(self.abs_ptr_bone_hierarchy_data)
        int16s_to_read = self.num_bone_hierarchy_data_lines * 8
        rw_operator('bone_hierarchy_data', 'h'*int16s_to_read)

    def rw_bone_data(self, rw_operator):
        # Rotation, position, scale as quaternions and affine vectors
        self.assert_file_pointer_now_at(self.abs_ptr_bone_defs)
        floats_to_read = self.num_bones * 12  # * 4
        rw_operator('bone_data', 'f'*floats_to_read)

    def rw_parent_bones(self, rw_operator):
        self.assert_file_pointer_now_at(self.abs_ptr_parent_bones)
        rw_operator('parent_bones', 'h'*self.num_bones, force_1d=True)

    def rw_unknown_data_1(self, rw_operator):
        #self.assert_file_pointer_now_at()
        rw_operator('unknown_data_1', 'B'*self.unknown_0x0C, force_1d=True)

    def rw_unknown_data_2(self, rw_operator):
        self.assert_file_pointer_now_at(self.abs_ptr_unknown_2)
        bytes_to_read = self.num_bones * 4
        # B, H, I, e, f all seem to give nonsensical results...
        # Changing the endianness doesn't help
        # Could be a float normalised in the range [-1, 1] using int16s (or equiv. for uint16)
        rw_operator('unknown_data_2', 'HH'*self.num_bones)
        # self.unknown_data_2 = self.decode_data_as('I', self.bytestream.read(bytes_to_read), endianness='<')
        # self.unknown_data_2 = [elem / 2**32 for elem in self.unknown_data_2]

    def rw_unknown_data_3(self, rw_operator):
        self.assert_file_pointer_now_at(self.abs_ptr_unknown_3)
        #bytes_to_read = self.unknown_0x0C * 4
        # Looks like uint32s, no idea what these are for though.
        rw_operator('unknown_data_3', 'I'*self.unknown_0x0C)

    def rw_unknown_data_4(self, rw_operator):
        # ???
        rw_operator('unknown_data_4', 'HH'*self.unknown_0x0C)

    def interpret_skel_data(self):
        self.bone_hierarchy_data = self.chunk_list(self.bone_hierarchy_data, 8)
        self.bone_data = self.chunk_list(self.chunk_list(self.bone_data, 4), 3)
        self.parent_bones = [(i, idx) for i, idx in enumerate(self.parent_bones)]
        # Basic error checking - make sure no bone idx exceeds the known number of bones
        if len(self.parent_bones) != 0:
            max_idx = max([subitem for item in self.parent_bones for subitem in item])
        else:
            max_idx = -1
        assert max_idx == self.num_bones - 1, f'{max_idx}, {self.num_bones - 1}'
        
        # final elem of 'pos' and 'scale' always 1 - these are nominally 4-vectors,
        # so the final elem is presumably either unused or part of an affine transform
        for i, bone_set in enumerate(self.bone_data):
            assert bone_set[1][-1] == 1., bone_set
            assert bone_set[2][-1] == 1., bone_set

    def reinterpret_skel_data(self):
        self.bone_hierarchy_data = self.flatten_list(self.bone_hierarchy_data)
        self.bone_data = self.flatten_list(self.flatten_list(self.bone_data))
        self.parent_bones = [parent for child, parent in self.parent_bones]
