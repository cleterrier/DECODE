import torch
import time

from tqdm import tqdm

from .utils import log_train_val_progress
from ..generic import emitter


def train(model, optimizer, loss, dataloader, grad_rescale, epoch, device, logger):

    """Some Setup things"""
    model.train()
    tqdm_enum = tqdm(dataloader, total=len(dataloader), smoothing=0.)  # progress bar enumeration
    t0 = time.time()

    """Actual Training"""
    for batch_num, (x, y_tar, weight) in enumerate(tqdm_enum):  # model input (x), target (yt), weights (w)

        """Monitor time to get the data"""
        t_data = time.time() - t0

        """Ship the data to the correct device"""
        x, y_tar, weight = x.to(device), y_tar.to(device), weight.to(device)

        """Forward the data"""
        y_out = model(x)

        """Reset the optimiser, compute the loss and backprop it"""
        optimizer.zero_grad()
        loss_val = loss(y_out, y_tar, weight)

        if grad_rescale:  # rescale gradients so that they are in the same order for the last layer
            weight, _, _ = model.rescale_last_layer_grad(loss_val, optimizer)
            loss_val = loss_val * weight

        loss_val.mean().backward()

        """Update model parameters"""
        optimizer.step()

        """Monitor overall time"""
        t_batch = time.time() - t0

        """Logging"""
        loss_mean, loss_cmp = loss.log(loss_val)  # compute individual loss components
        tqdm_enum.set_description(f"E: {epoch} - t: {t_batch:.2} - t_dat: {t_data:.2} - L: {loss_mean:.3}")

        log_train_val_progress.log_train(loss_mean, t_batch, t_data, epoch, batch_num, 10, model, logger)

    return


def test(model, optimizer, loss, dataloader, grad_rescale, post_processor, epoch, device, logger):

    """Setup"""
    x_ep, y_out_ep, y_tar_ep, weight_ep, em_tar_ep = [], [], [], [], []  # store things epoche wise (_ep)
    loss_cmp_ep = []

    model.eval()
    tqdm_enum = tqdm(dataloader, total=len(dataloader), smoothing=0.)  # progress bar enumeration

    t0 = time.time()

    """Testing"""
    with torch.no_grad():
        for batch_num, (x, y_tar, weight, em_tar) in enumerate(tqdm_enum):

            """Ship the data to the correct device"""
            x, y_tar, weight = x.to(device), y_tar.to(device), weight.to(device)

            """Forward the data"""
            y_out = model(x)

            loss_val = loss(y_out, y_tar, weight)

            if grad_rescale:  # rescale gradients so that they are in the same order for the last layer
                weight, _, _ = model.rescale_last_layer_grad(loss_val, optimizer)
                loss_val = loss_val * weight

            t_batch = time.time() - t0

            """Logging and temporary save"""
            tqdm_enum.set_description(f"(Test) E: {epoch} - T: {t_batch:.2}")

            loss_cmp_ep.append(loss_val.detach().cpu())
            x_ep.append(x.cpu())
            y_out_ep.append(y_out.detach().cpu())
            y_tar_ep.append(y_tar.detach().cpu())
            weight_ep.append(weight.detach().cpu())
            # because the training samples are all on frame 0
            em_tar_ep.append(emitter.EmitterSet.cat(em_tar, step_frame_ix=1))

    """Epoch-Wise Merging and Post-Processing"""
    print(f"(Test) E: {epoch} - Post-Processing and Evaluation.", flush=True)
    loss_cmp_ep = torch.cat(loss_cmp_ep, 0)
    x_ep = torch.cat(x_ep, 0)
    y_out_ep = torch.cat(y_out_ep, 0)
    em_tar_ep = emitter.EmitterSet.cat(em_tar_ep, step_frame_ix=dataloader.batch_size)
    y_tar_ep = torch.cat(y_tar_ep, 0)
    weight_ep = torch.cat(weight_ep, 0)

    em_out_ep = post_processor.forward(y_out_ep)

    log_train_val_progress.log_val(loss_cmp_ep, x_ep, y_out_ep, y_tar_ep, weight_ep, em_out_ep, em_tar_ep,
                                   epoch, logger)

    return