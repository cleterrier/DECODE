import datetime
import os
import time
from comet_ml import Experiment, OfflineExperiment

import torch
from tensorboardX import SummaryWriter
from torch.optim import Adam
from torch.optim.lr_scheduler import ReduceLROnPlateau
from torch.utils.data import DataLoader

from deepsmlm.generic.inout.load_calibration import SMAPSplineCoefficient
from deepsmlm.generic.inout.load_save_emitter import NumpyInterface
from deepsmlm.generic.inout.load_save_model import LoadSaveModel
from deepsmlm.generic.noise import Poisson
from deepsmlm.generic.psf_kernel import ListPseudoPSFInSize, DeltaPSF
from deepsmlm.generic.utils.data_utils import smlm_collate
from deepsmlm.generic.utils.scheduler import ScheduleSimulation
from deepsmlm.neuralfitter.arguments import InOutParameter, HyperParamter, SimulationParam, LoggerParameter, \
    SchedulerParameter
from deepsmlm.neuralfitter.dataset import SMLMDataset
from deepsmlm.neuralfitter.dataset import SMLMDatasetOnFly
from deepsmlm.neuralfitter.losscollection import MultiScaleLaplaceLoss, BumpMSELoss
from deepsmlm.neuralfitter.models.model import DenseLoco, USMLM, USMLMLoco
from deepsmlm.neuralfitter.pre_processing import N2C, SingleEmitterOnlyZ
from deepsmlm.neuralfitter.train_test import train, test
from deepsmlm.simulator.emittergenerator import EmitterPopper, EmitterPopperMultiFrame
from deepsmlm.simulator.structure_prior import RandomStructure
from deepsmlm.simulator.simulator import Simulation

"""Root folder"""
deepsmlm_root = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 os.pardir, os.pardir)) + '/'


if __name__ == '__main__':

    """Set ur basic parameters"""
    io_par = InOutParameter(
        root=deepsmlm_root,
        log_comment='',
        data_mode='online',
        data_set=None,  # deepsmlm_root + 'data/2019-03-26/complete_z_range.npz',
        model_out=deepsmlm_root + 'network/2019-04-09/combined_net_corrected_sigmas_singleframefordenseloco.pt',
        model_init=None)

    log_par = LoggerParameter(
        tags=['3D', 'Coords', 'DenseNet'])

    sched_par = SchedulerParameter(
        lr_factor=0.1,
        lr_patience=10,
        lr_threshold=0.0025,
        lr_cooldown=10,
        lr_verbose=True,
        sim_factor=1,
        sim_patience=1,
        sim_threshold=0,
        sim_cooldown=10,
        sim_verbose=True,
        sim_disabled=True,
        sim_max_value=50,
    )

    hy_par = HyperParamter(
        dimensions=3,
        channels=3,
        max_emitters=64,
        min_phot=600.,
        data_lifetime=10,
        upscaling=8,
        upscaling_mode='nearest',
        batch_size=32,
        test_size=256,
        num_epochs=10000,
        lr=1E-4,
        device=torch.device('cuda'))

    sim_par = SimulationParam(
        pseudo_data_size=(256*32 + 256),  # (256*256 + 512),
        emitter_extent=((-0.5, 31.5), (-0.5, 31.5), (-500, 500)),
        psf_extent=((-0.5, 31.5), (-0.5, 31.5), (-750., 750.)),
        img_size=(32, 32),
        density=0,
        emitter_av=15,
        photon_range=(4000, 8000),
        bg_pois=15,
        calibration=deepsmlm_root +
                    'data/Cubic Spline Coefficients/2019-02-20/60xOil_sampleHolderInv__CC0.140_1_MMStack.ome_3dcal.mat')

    """Log System"""
    log_dir = deepsmlm_root + 'log/' + str(datetime.datetime.now())[:16]

    experiment = Experiment(project_name='deepsmlm', workspace='haydnspass',
                            auto_metric_logging=False, disabled=True)
    # experiment = OfflineExperiment(project_name='deepsmlm',
    #                                workspace='haydnspass',
    #                                auto_metric_logging=False,
    #                                offline_directory=deepsmlm_root + 'log/')
    experiment.log_parameters(hy_par._asdict(), prefix='Hyp')
    experiment.log_parameters(sim_par._asdict(), prefix='Sim')
    experiment.log_parameters(sched_par._asdict(), prefix='Sched')
    experiment.log_parameters(io_par._asdict(), prefix='IO')
    experiment.log_parameters(log_par._asdict(), prefix='Log')

    """Add some tags as specified above."""
    for tag in log_par.tags:
        experiment.add_tag(tag)

    logger = SummaryWriter(log_dir, comment=io_par.log_comment)
    logger.add_text('comet_ml_key', experiment.get_key())

    """Set target for the Neural Network."""
    target_generator = ListPseudoPSFInSize(sim_par.emitter_extent[0], sim_par.emitter_extent[1],
                                           sim_par.emitter_extent[2], zts=hy_par.max_emitters, dim=3,
                                           photon_threshold=hy_par.min_phot)

    # target_generator = DeltaPSF(xextent=sim_par.psf_extent[0],
    #                             yextent=sim_par.psf_extent[1],
    #                             zextent=None,
    #                             img_shape=(sim_par.img_size[0] * hy_par.upscaling,
    #                                        sim_par.img_size[1] * hy_par.upscaling),
    #                             photon_threshold=hy_par.min_phot,
    #                             photon_normalise=True)

    if io_par.data_mode == 'precomputed':
        """Load Data from binary."""
        emitter, extent, frames = NumpyInterface().load_binary(io_par.data_set)

        data_smlm = SMLMDataset(emitter, extent, frames, target_generator,
                                multi_frame_output=False,
                                dimensionality=None)

        train_size = data_smlm.__len__() - hy_par.test_size
        train_data_smlm, test_data_smlm = torch.utils.data.random_split(data_smlm, [train_size, hy_par.test_size])

        train_loader = DataLoader(train_data_smlm,
                                  batch_size=hy_par.batch_size, shuffle=True, num_workers=24, pin_memory=True)

        test_loader = DataLoader(test_data_smlm,
                                 batch_size=hy_par.test_size, shuffle=False, num_workers=12, pin_memory=True)

    elif io_par.data_mode == 'online':
        """Load 'Dataset' which is generated on the fly."""
        smap_psf = SMAPSplineCoefficient(sim_par.calibration)
        psf = smap_psf.init_spline(sim_par.psf_extent[0], sim_par.psf_extent[1], sim_par.img_size)
        noise = Poisson(bg_uniform=sim_par.bg_pois)

        structure_prior = RandomStructure(sim_par.emitter_extent[0],
                                          sim_par.emitter_extent[1],
                                          sim_par.emitter_extent[2])

        # prior = EmitterPopper(structure_prior,
        #                       density=sim_par.density,
        #                       photon_range=sim_par.photon_range,
        #                       emitter_av=sim_par.emitter_av)

        prior = EmitterPopperMultiFrame(structure_prior,
                                        density=sim_par.density,
                                        photon_range=sim_par.photon_range,
                                        lifetime=1,
                                        num_frames=3,
                                        emitter_av=sim_par.emitter_av)

        if hy_par.channels == 3:
            frame_range = (-1, 1)
        elif hy_par.channels == 1:
            frame_range = (0, 0)
        else:
            raise ValueError("Channels must be 1 (for only target frame) or 3 for one adjacent frame.")

        simulator = Simulation(None,
                               sim_par.emitter_extent,
                               psf,
                               noise,
                               poolsize=0,
                               frame_range=frame_range)

        input_preparation = N2C()

        train_size = sim_par.pseudo_data_size - hy_par.test_size

        train_data_smlm = SMLMDatasetOnFly(None, prior, simulator, train_size,
                                           input_preparation, target_generator, None, static=False,
                                           lifetime=hy_par.data_lifetime)

        test_data_smlm = SMLMDatasetOnFly(None, prior, simulator, hy_par.test_size,
                                          input_preparation, target_generator, None, static=True)

        train_loader = DataLoader(train_data_smlm,
                                  batch_size=hy_par.batch_size,
                                  shuffle=True,
                                  num_workers=0,
                                  pin_memory=True,
                                  collate_fn=smlm_collate)

        test_loader = DataLoader(test_data_smlm,
                                 batch_size=hy_par.batch_size,
                                 shuffle=False,
                                 num_workers=0,
                                 pin_memory=True,
                                 collate_fn=smlm_collate)

    else:
        raise NameError("You used the wrong switch of how to get the training data.")

    """Model load and save interface."""
    # model = DenseLoco(extent=sim_par.psf_extent,
    #                   ch_in=hy_par.channels,
    #                   dim_out=hy_par.dimensions,
    #                   max_num_emitter=hy_par.max_emitters)
    # model = USMLM(in_ch=hy_par.channels, upsampling=hy_par.upscaling, upsampling_mode=hy_par.upscaling_mode)
    # model = SuperDumbFCNet(289, (-750., 750.))

    model_usmlm = USMLM(in_ch=hy_par.channels,
                        upsampling=hy_par.upscaling,
                        upsampling_mode=hy_par.upscaling_mode)

    # TODO: bit hacky. Reduce hard coded stuff here.
    usmlm_file = deepsmlm_root + 'network/2019-04-07/model_multi_frame_13.pt'
    model_usmlm = LoadSaveModel(model_usmlm, output_file=None, input_file=usmlm_file).load_init()

    model = USMLMLoco(model_usmlm,
                      in_ch=hy_par.channels,
                      extent=sim_par.psf_extent,
                      dim_out=hy_par.dimensions,
                      max_num_emitter=hy_par.max_emitters,
                      densenet_out=2048)

    """Log the model"""
    try:
        dummy = torch.rand((2, 3, *sim_par.img_size), requires_grad=True)
        logger.add_graph(model, dummy, False)
    except:
        print("Your dummy input is wrong. Please update it.")

    model_ls = LoadSaveModel(model, output_file=io_par.model_out, input_file=io_par.model_init)
    model = model_ls.load_init()
    model = model.to(hy_par.device)

    optimiser = Adam(model.parameters(), lr=hy_par.lr)

    """Loss function."""
    # kernel_sigmas = (0.64, 3.20, 6.4, 19.2)
    kernel_sigmas_upscaled = (5.12, 25.6, 51.2, 153.6)
    experiment.log_parameter('Loss/kernel_sigmas', kernel_sigmas_upscaled)
    criterion = MultiScaleLaplaceLoss(kernel_sigmas=kernel_sigmas_upscaled).return_criterion()
    # criterion = BumpMSELoss(kernel_sigma=1.5, cuda=True, l1_f=0).return_criterion()

    # sc_cluster=0.5
    # experiment.log_parameter('Loss/scale_cluster_reduce', sc_cluster)
    # criterion = MultiSLLRedClus(kernel_sigmas=kernel_sigmas, loc=0.15, scale=0.03, phot_loss_sc=sc_cluster).return_criterion()

    """Learning Rate Scheduling"""
    lr_scheduler = ReduceLROnPlateau(optimiser,
                                     mode='min',
                                     factor=sched_par.lr_factor,
                                     patience=sched_par.lr_patience,
                                     threshold=sched_par.lr_threshold,
                                     cooldown=sched_par.lr_cooldown,
                                     verbose=sched_par.lr_verbose)

    sim_scheduler = ScheduleSimulation(prior=prior,
                                       datasets=[train_data_smlm, test_data_smlm],
                                       optimiser=optimiser,
                                       threshold=sched_par.sim_threshold,
                                       step_size=sched_par.sim_factor,
                                       max_emitter=sched_par.sim_max_value,
                                       patience=sched_par.sim_patience,
                                       cooldown=sched_par.sim_cooldown)

    last_new_model_name_time = time.time()

    """Ask if everything is correct before we start."""
    for i in range(hy_par.num_epochs):
        logger.add_scalar('learning/learning_rate', optimiser.param_groups[0]['lr'], i)
        experiment.log_metric('learning/learning_rate', optimiser.param_groups[0]['lr'], i)

        train(train_loader, model, optimiser, criterion, i, hy_par, logger, experiment, train_data_smlm.calc_new_flag)

        val_loss = test(test_loader, model, criterion, i, hy_par, logger, experiment, None)
        lr_scheduler.step(val_loss)
        sim_scheduler.step(val_loss)

        """When using online generated data, reduce lifetime."""
        if io_par.data_mode == 'online':
            train_data_smlm.step()

        """Give the output file a new suffix every hour (i.e. _0, _1, _2 ...)"""
        if time.time() > last_new_model_name_time + 60*60:
            trigger_new_name = True
            last_new_model_name_time = time.time()
        else:
            trigger_new_name = False

        model_ls.save(model, trigger_new_name)

    experiment.end()
