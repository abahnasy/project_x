""" read the segments and create annotations needed for tracking the tracker
    Author: Ahmed Bahnasy
"""
# steps:
# read segment
# create annotations
import os, logging, pickle, time
from torch._C import Value
from torch.utils.data.dataloader import DataLoader

from tqdm import tqdm
import hydra
from omegaconf import DictConfig, OmegaConf
from addict import Dict
import numpy as np
import torch
from torch.utils.tensorboard import SummaryWriter

from tracking.utils import reorganize_info, transform_box
from viz_predictions import get_obj
from utils.visualizations import get_corners_from_labels_array

from tools.profiler import AdvancedProfiler
prof = AdvancedProfiler("profiler_ouput.txt")

from tracking.models import *

def in_hull(p, hull):
    from scipy.spatial import Delaunay
    if not isinstance(hull,Delaunay):
        hull = Delaunay(hull)
    return hull.find_simplex(p)>=0

def extract_pc_in_box3d(pc, box3d):
    ''' pc: (N,3), box3d: (8,3) '''
    box3d_roi_inds = in_hull(pc[:,0:3], box3d)
    return pc[box3d_roi_inds,:], box3d_roi_inds
# ================================ #
# Point Cloud Sampling
# ================================ #
def random_sampling(pc, num_sample, replace=None, return_choices=False):
    """ Input is NxC, output is num_samplexC
    """
    if replace is None: replace = (pc.shape[0]<num_sample)
    choices = np.random.choice(pc.shape[0], num_sample, replace=replace)
    if return_choices:
        return pc[choices], choices
    else:
        return pc[choices]

# A logger for this file
log = logging.getLogger(__name__)

# Writer will output to ./runs/ directory by default
writer = SummaryWriter()

@hydra.main(config_path="conf_tracking", config_name="config")
def main(cfg : DictConfig) -> None:
    working_dir = os.getcwd()
    main_dir = hydra.utils.get_original_cwd()
    log.info("Training GNN")
    log.debug("Debug level message")


    # create dataset and dataloader
    from tracking.dataloader import TrackerDataset
    ds = TrackerDataset(cfg.info_path)
    dataloader = DataLoader(ds, batch_size=1, shuffle = False, num_workers=8)
    
    # create model
    from tracking.tracker_gnn import GNNMOT
    model = GNNMOT(cfg.model_configurations).cuda()

    print(model)


    optimizer = torch.optim.Adam([
        {'params': model.appear_extractor.parameters()},
        {'params': model.det_motion_extractor.parameters()},
        {'params': model.track_motion_extractor.parameters()},
        {'params': model.graph_conv.parameters()},
        # {'params': model.gnn_conv1.parameters()},
        # {'params': model.gnn_conv2.parameters()},
        # {'params': model.gnn_conv3.parameters()},
        # {'params': model.gnn_conv4.parameters()},
        {'params': model.edge_regr.parameters(), 'lr': 0.01},
    ],lr=0.0001)
    

    # training loop
    for epoch in range(cfg.max_epochs):
        base_step =  epoch*len(ds)
        for i, data_bundle in enumerate(dataloader):
            print("DEBUG: memory allocated: ", torch.cuda.memory_allocated() / torch.cuda.max_memory_allocated())
            
            
            # if i == 10:
                # prof.describe()
                # exit()

            optimizer.zero_grad()
            
            batch_size = data_bundle['det_boxes3d'].shape[0]
            assert batch_size == 1, "currrently, only one item in the batch is processed"
            # loss
            N = data_bundle['det_boxes3d'][0].shape[0]
            M = data_bundle['track_boxes3d'][0].shape[0]
            
            # writer.add_graph(
            #     model, 
            #     [
            #         data_bundle['det_pc_in_box'][0].cuda(), 
            #         data_bundle['det_boxes3d'][0].cuda(), # torch.from_numpy(det_data['boxes3d']).float().cuda(),
            #         data_bundle['track_pc_in_box'][0].cuda(), # track_pc_in_box, 
            #         data_bundle['track_boxes3d'][0].cuda(), # track_boxes3d.cuda(), 
            #         data_bundle['graph_adj_matrix'][0].cuda(), # graph_adj_matrix,
            #         data_bundle['gt_affinity_matrix'][0].cuda(), # gt_affinity_matrix.cuda(),
            #     ]
            # )
            # exit()
            # with prof.profile("forward pass"):
            tick = time.time()
            data_bundle = {
                'det_pc_in_box':data_bundle['det_pc_in_box'][0].cuda(),
                'det_boxes3d':data_bundle['det_boxes3d'][0].cuda(),
                'track_pc_in_box':data_bundle['track_pc_in_box'][0].cuda(),
                'track_boxes3d':data_bundle['track_boxes3d'][0].cuda(),
                'init_aff_matrix':data_bundle['init_aff_matrix'][0].cuda(),
                'gt_affinity_matrix':data_bundle['gt_affinity_matrix'][0].cuda()
            }
            
            
            loss, aff_loss, triplet_loss, affinity_matrix = model(
                data_bundle['det_pc_in_box'], 
                data_bundle['det_boxes3d'], # torch.from_numpy(det_data['boxes3d']).float().cuda(),
                data_bundle['track_pc_in_box'], # track_pc_in_box, 
                data_bundle['track_boxes3d'], # track_boxes3d.cuda(), 
                data_bundle['init_aff_matrix'], # graph_adj_matrix,
                data_bundle['gt_affinity_matrix'], # gt_affinity_matrix.cuda(),
            )
            
            
            print("Forwad and Loss time: ", time.time() - tick)
            assert affinity_matrix.shape == (N, M)
            # backward
            print(loss.item())
            if loss.item() < 0:
                raise ValueError("Negative loss value !!!!")
            writer.add_scalar('Loss/train/total', loss.item(), base_step + i)
            writer.add_scalar('Loss/train/triplet', triplet_loss.item(), base_step + i)
            writer.add_scalar('Loss/train/aff', aff_loss.item(), base_step + i)
            
            loss.backward()
            # update optimizer
            optimizer.step()
            
            

            # # prints currently alive Tensors and Variables
            # import gc
            # log.info("==== End of Iteration Memory debugging ====")
            # for obj in gc.get_objects():
            #     try:
            #         if torch.is_tensor(obj) or (hasattr(obj, 'data') and torch.is_tensor(obj.data)):
            #             log.info("{}, {}".format(type(obj), obj.size()))
            #     except:
            #         pass
        torch.save(model.state_dict(), "epoch_{}.pt".format(epoch))
    
    


if __name__ == '__main__':
    main()




"""
    box3d[:, -1] = -box3d[:, -1] - np.pi / 2
    box3d[:, [3, 4]] = box3d[:, [4, 3]]
    # box3d in global coordinates
    box3d_glob = transform_box(box3d, pose)
    # get frame id
    frame_id = token.split('_')[3][:-4]
    num_box = len(box3d)
    anno_list =[]
    for i in range(num_box):
        anno = {
            'translation': box3d[i, :3],
            'translation_glob': box3d_glob[i,:3],
            'velocity': box3d[i, [6, 7]],
            'velocity_glob': box3d_glob[i, [6, 7]],
            'detection_name': info['gt_names'][i],
            'box_id': i,
            'box3d': box3d[i,:],
            'box3d_glob': box3d_glob[i,:]
        }

    anno_list.append(anno)
    record['token'] =  token
    record['frame_id'] = int(frame_id)
    record['boxes'] =  anno_list
    record['point_cloud'] =  pc
    record['timestamp'] =  info['timestamp']
"""