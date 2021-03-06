import os
from collections import OrderedDict
from terminaltables import AsciiTable

import torch


def load_state_dict(module, state_dict, strict=False, logger=None):
    """Load state_dict into a module
    """
    unexpected_keys = []
    shape_mismatch_pairs = []

    own_state = module.state_dict()
    for name, param in state_dict.items():
        # a hacky fixed to load a new voxelnet 
        if name not in own_state:
            unexpected_keys.append(name)
            continue
        if isinstance(param, torch.nn.Parameter):
            # backwards compatibility for serialized parameters
            param = param.data
        if param.size() != own_state[name].size():
            shape_mismatch_pairs.append([name, own_state[name].size(), param.size()])
            continue
        own_state[name].copy_(param)

    all_missing_keys = set(own_state.keys()) - set(state_dict.keys())
    # ignore "num_batches_tracked" of BN layers
    missing_keys = [key for key in all_missing_keys if "num_batches_tracked" not in key]

    err_msg = []
    if unexpected_keys:
        err_msg.append(
            "unexpected key in source state_dict: {}\n".format(
                ", ".join(unexpected_keys)
            )
        )
    if missing_keys:
        err_msg.append(
            "missing keys in source state_dict: {}\n".format(", ".join(missing_keys))
        )
    if shape_mismatch_pairs:
        mismatch_info = "these keys have mismatched shape:\n"
        header = ["key", "expected shape", "loaded shape"]
        table_data = [header] + shape_mismatch_pairs
        table = AsciiTable(table_data)
        err_msg.append(mismatch_info + table.table)

    
    if len(err_msg) > 0:
        err_msg.insert(0, "The model and loaded state dict do not match exactly\n")
        err_msg = "\n".join(err_msg)
        if strict:
            raise RuntimeError(err_msg)
        elif logger is not None:
            logger.warning(err_msg)
        else:
            print(err_msg)


def load_checkpoint(model, filename, map_location=None, strict=False, logger=None):
    """Load checkpoint from a file or URI.

    Args:
        model (Module): Module to load checkpoint.
        filename (str): Either a filepath or URL or modelzoo://xxxxxxx.
        map_location (str): Same as :func:`torch.load`.
        strict (bool): Whether to allow different params for the model and
            checkpoint.
        logger (:mod:`logging.Logger` or None): The logger for error message.

    Returns:
        dict or OrderedDict: The loaded checkpoint.
    """
    
    if not os.path.isfile(filename):
        raise IOError("{} is not a checkpoint file".format(filename))
    checkpoint = torch.load(filename, map_location=map_location)
    # get state_dict from checkpoint
    if isinstance(checkpoint, OrderedDict):
        state_dict = checkpoint
    elif isinstance(checkpoint, dict) and "state_dict" in checkpoint:
        state_dict = checkpoint["state_dict"]
    else:
        raise RuntimeError("No state_dict found in checkpoint file {}".format(filename))
    # strip prefix of state_dict
    if list(state_dict.keys())[0].startswith("module."):
        state_dict = {k[7:]: v for k, v in checkpoint["state_dict"].items()}
    # load state_dict
    if hasattr(model, "module"):
        load_state_dict(model.module, state_dict, strict, logger)
    else:
        load_state_dict(model, state_dict, strict, logger)
        print("Model state Dict loaded")
    return checkpoint



def weights_to_cpu(state_dict):
    state_dict_cpu = OrderedDict()
    for k, v in state_dict.items():
        state_dict_cpu[k] = v.cpu()
    return state_dict_cpu
    
def save_checkpoint(working_dir, model, optimizer, meta):
    '''
    meta = dict(epoch=self.epoch + 1, iter=self.iter)
    '''

    if not os.path.exists(working_dir):
        raise NotADirectoryError

    filename = 'epoch_{}.pth'.format(meta['epoch'])
    filepath = os.path.join(working_dir, filename)
    filelink = os.path.join(working_dir, 'latest.pth')
    checkpoint = {
        'meta': meta,
        'state_dict': weights_to_cpu(model.state_dict()),
        'optimizer': optimizer.state_dict()
    }
    torch.save(checkpoint, filepath)
    # create symlink to the latest epoch
    if os.path.lexists(filelink):
        os.remove(filelink)
    os.symlink(filepath, filelink)