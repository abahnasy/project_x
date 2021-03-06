'''REF: https://github.com/slam-research-group-kr/SECOND-ROS/blob/150cae25dc706cded203bb462a0ac6325dab4b78/second/pytorch/models/voxel_encoder.py
'''
from torch import nn
from torch.nn import functional as F

from models.registry import READERS





@READERS.register_module
class VoxelFeatureExtractorV3(nn.Module):
    def __init__(
        self, num_input_features=4, norm_cfg=None, name="VoxelFeatureExtractorV3", **kwargs
    ):
        super(VoxelFeatureExtractorV3, self).__init__()
        self.name = name
        self.num_input_features = num_input_features

    def forward(self, features, num_voxels, coors=None):
        '''
        Args: 
            features: voxels
            num_voxels: total num of extracted voxels
        Returns:

        '''
        assert self.num_input_features == features.shape[-1]

        points_mean = features[:, :, : self.num_input_features].sum(
            dim=1, keepdim=False
        ) / num_voxels.type_as(features).view(-1, 1)

        return points_mean.contiguous()
