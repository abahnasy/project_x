import torch
import torch.nn as nn
import torch.nn.functional as F
from dgl.nn import EdgeConv

from tracking.models.registry import CONV_OPERATORS
from tools.builder import build_from_cfg_dict

from tracking.models.losses.affinity_loss import AffinityLoss
from tracking.models.losses.triplet_loss import TripletLoss
from tracking.models.registry import EDGE_REGRESSORS

@CONV_OPERATORS.register_module
class EdgeConvOp(nn.Module):
    """ https://arxiv.org/pdf/1801.07829
    """
    
    def __init__(
        self, 
        feature_size=128, 
        num_gnn_layers=4, 
        activation='relu',
        loss_every_layer = True,
        edge_regression = None,
        mode = 'train',
        **kwargs):

        super(EdgeConvOp, self).__init__()
        self.mode = mode
        self.feature_size = feature_size
        self.num_gnn_layers = num_gnn_layers
        self.loss_every_layer = loss_every_layer
        self.affinity_loss = AffinityLoss()
        self.triplet_loss = TripletLoss(margin=10)
        self.edge_regr = build_from_cfg_dict(edge_regression, EDGE_REGRESSORS)
        
        # ASSERTIONS !
        assert self.edge_regr != None
        
        
        self.graph_conv_layers = nn.ModuleList([
            EdgeConv(self.feature_size, self.feature_size) for _ in range(self.num_gnn_layers)
        ])
        self.activation = nn.ReLU() if activation == 'relu' else nn.Tanh()
    
    def forward(self, graph, embeddings, gt_aff_mat, N, M):
        """
        Args:
            graph: Graph
            Node Embeddings
            Ground Truth Affinity Matrix
            # Detected Objects
            # Tracked Objects
        Return: 
            Last Layer Loss or Total Layer Losses
            Regressed Affinity Matrix
        """
        
        triplet_layers_loss = torch.zeros(1).cuda()
        aff_layers_loss = torch.zeros(1).cuda()
        ret_dict = {}

        # Node Aggregations
        for layer in self.graph_conv_layers:
            embeddings = layer(graph, embeddings)
            embeddings = self.activation(embeddings)
            if self.loss_every_layer:
                pred_aff_mat = self._regress_aff_mat(embeddings, N, M)
                if self.mode == 'train':
                    aff_layers_loss += self.affinity_loss(pred_aff_mat, gt_aff_mat)
                    triplet_layers_loss += self.triplet_loss(embeddings, gt_aff_mat)
        
        # calculate Loss based on final layer if loss every layer is not True
        if not self.loss_every_layer:
            pred_aff_mat = self._regress_aff_mat(embeddings, N, M)
            if self.mode == 'train':
                aff_layers_loss += self.affinity_loss(pred_aff_mat, gt_aff_mat)
                triplet_layers_loss += self.triplet_loss(embeddings, gt_aff_mat)
        
        if self.mode == 'train':
            # Return Loss/Total Loss Tensor
            ret_dict['total_loss'] = triplet_layers_loss + aff_layers_loss
            ret_dict['triplet_loss'] = triplet_layers_loss.detach()
            ret_dict['aff_loss'] = aff_layers_loss.detach()
            return ret_dict, pred_aff_mat
        else:
            return pred_aff_mat

    def _regress_aff_mat(self, embeddings, N, M):
        # vectorization
        edges = (embeddings[N:N+M].reshape(M,256).unsqueeze(0) - embeddings[0:N].reshape(N,256).unsqueeze(1)).reshape(N*M, 256)
        edges = self.edge_regr(edges)
        return edges.reshape(N,M) # regressed affinity matrix


if __name__ == '__main__':
    model = EdgeConvOp()
    
    import torch, dgl
    h = torch.rand(10, 128)
    G = dgl.graph(data = ([1,2,3,4,5], [6,7,8,9,0]), num_nodes=10)
    G = dgl.add_self_loop(G)
    output = model(G, h)
    print(output.min(), output.max())


