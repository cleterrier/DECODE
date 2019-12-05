import torch
from torch import nn as nn

from deepsmlm.neuralfitter.models.unet_param import UNet2d
import deepsmlm.neuralfitter.utils.last_layer_dynamics as lyd


class SimpleSMLMNet(UNet2d):
    def __init__(self, ch_in, ch_out, depth=3, initial_features=64, inter_features=64, p_dropout=0.,
                 activation=nn.ReLU(), use_last_nl=True, norm=None, norm_groups=None):
        super().__init__(in_channels=ch_in,
                         out_channels=ch_out,
                         depth=depth,
                         initial_features=initial_features,
                         pad_convs=True,
                         norm=norm,
                         norm_groups=norm_groups,
                         p_dropout=p_dropout,
                         activation=activation)

        assert ch_out in (5, 6)
        self.ch_out = ch_out
        self.mt_heads = nn.ModuleList([MLTHeads(inter_features, norm=norm) for _ in range(self.ch_out)])

        self._use_last_nl = use_last_nl

        self.p_nl = torch.sigmoid  # only in inference, during training
        self.phot_nl = torch.sigmoid
        self.xyz_nl = torch.tanh
        self.bg_nl = torch.sigmoid

    @staticmethod
    def parse(param):
        activation = eval(param['HyperParameter']['arch_param']['activation'])
        return SimpleSMLMNet(
            ch_in=param['HyperParameter']['channels_in'],
            ch_out=param['HyperParameter']['channels_out'],
            depth=param['HyperParameter']['arch_param']['depth'],
            initial_features=param['HyperParameter']['arch_param']['initial_features'],
            inter_features=param['HyperParameter']['arch_param']['inter_features'],
            p_dropout=param['HyperParameter']['arch_param']['p_dropout'],
            activation=activation,
            use_last_nl=param['HyperParameter']['arch_param']['use_last_nl'],
            norm=param['HyperParameter']['arch_param']['norm'],
            norm_groups=param['HyperParameter']['arch_param']['norm_groups']
        )

    def apply_pnl(self, o):
        """
        Apply nonlinearity (sigmoid) to p channel. This is combined during training in the loss function.
        Only use when not training
        :param o:
        :return:
        """
        o[:, [0]] = self.p_nl(o[:, [0]])
        return o

    def apply_nonlin(self, o):
        """
        Apply non linearity in all the other channels
        :param o:
        :return:
        """
        # Apply for phot, xyz
        p = o[:, [0]]  # leave unused
        phot = o[:, [1]]
        xyz = o[:, 2:5]

        phot = self.phot_nl(phot)
        xyz = self.xyz_nl(xyz)

        if self.ch_out == 5:
            o = torch.cat((p, phot, xyz), 1)
            return o
        elif self.ch_out == 6:
            bg = o[:, [5]]
            bg = self.bg_nl(bg)

            o = torch.cat((p, phot, xyz, bg), 1)
            return o

    def forward(self, x):
        o = super().forward(x)

        o_head = []
        for i in range(self.ch_out):
            o_head.append(self.mt_heads[i].forward(o))
        o = torch.cat(o_head, 1)

        """Apply the final non-linearities"""
        if not self.training:
            p = self.p_nl(p)

        if self._use_last_nl:
            o = self.apply_nonlin(o)

        return o


class SMLMNetBG(SimpleSMLMNet):
    def __init__(self, ch_in, ch_out, depth=3, initial_features=64, inter_features=64, p_dropout=0.,
                 activation=nn.ReLU(), use_last_nl=True, norm=None, norm_groups=None, norm_bg=None,
                 norm_bg_groups=None, detach_bg=False):

        super().__init__(ch_in + 1, ch_out - 1, depth, initial_features, inter_features, p_dropout, activation,
                         use_last_nl,
                         norm, norm_groups)
        assert ch_out == 6
        self.total_ch_out = ch_out
        self.detach_bg = detach_bg

        self.bg_net = UNet2d(1, 1, 2, 48, pad_convs=True, norm=norm_bg, norm_groups=norm_bg_groups,
                             activation=activation)

    @staticmethod
    def parse(param):
        activation = eval(param['HyperParameter']['arch_param']['activation'])
        return SMLMNetBG(
            ch_in=param['HyperParameter']['channels_in'],
            ch_out=param['HyperParameter']['channels_out'],
            depth=param['HyperParameter']['arch_param']['depth'],
            initial_features=param['HyperParameter']['arch_param']['initial_features'],
            inter_features=param['HyperParameter']['arch_param']['inter_features'],
            p_dropout=param['HyperParameter']['arch_param']['p_dropout'],
            activation=activation,
            use_last_nl=param['HyperParameter']['arch_param']['use_last_nl'],
            norm=param['HyperParameter']['arch_param']['norm'],
            norm_groups=param['HyperParameter']['arch_param']['norm_groups'],
            norm_bg=param['HyperParameter']['arch_param']['norm_bg'],
            norm_bg_groups=param['HyperParameter']['arch_param']['norm_bg_groups'],
            detach_bg=param['HyperParameter']['arch_param']['detach_bg']
        )

    def forward(self, x):
        bg = self.bg_net.forward(x)
        if self.detach_bg:
            xbg = torch.cat((x, bg.detach()), 1)
        else:
            xbg = torch.cat((x, bg), 1)

        x = super().forward(xbg)
        return x


class DoubleMUnet(nn.Module):
    def __init__(self, ch_in, ch_out, ext_features=0, depth=3, initial_features=64, inter_features=64,
                 activation=nn.ReLU(), use_last_nl=True, norm=None, norm_groups=None):
        super().__init__()

        self.unet_shared = UNet2d(1 + ext_features, inter_features, depth=depth, pad_convs=True,
                                  initial_features=initial_features,
                                  activation=activation, norm=norm, norm_groups=norm_groups)
        self.unet_union = UNet2d(ch_in * inter_features, inter_features, depth=depth, pad_convs=True,
                                 initial_features=initial_features,
                                 activation=activation, norm=norm, norm_groups=norm_groups)

        assert ch_out in (5, 6)
        self.ch_out = ch_out
        self.mt_heads = nn.ModuleList([MLTHeads(inter_features, norm=norm) for _ in range(self.ch_out)])

        self._use_last_nl = use_last_nl

        self.p_nl = torch.sigmoid  # only in inference, during training
        self.phot_nl = torch.sigmoid
        self.xyz_nl = torch.tanh
        self.bg_nl = torch.sigmoid

    @staticmethod
    def parse(param):
        activation = eval(param['HyperParameter']['arch_param']['activation'])
        return DoubleMUnet(
            ch_in=param['HyperParameter']['channels_in'],
            ch_out=param['HyperParameter']['channels_out'],
            ext_features=0,
            depth=param['HyperParameter']['arch_param']['depth'],
            initial_features=param['HyperParameter']['arch_param']['initial_features'],
            inter_features=param['HyperParameter']['arch_param']['inter_features'],
            activation=activation,
            use_last_nl=param['HyperParameter']['arch_param']['use_last_nl'],
            norm=param['HyperParameter']['arch_param']['norm'],
            norm_groups=param['HyperParameter']['arch_param']['norm_groups']
        )

    def rescale_last_layer_grad(self, loss, optimizer):
        """

        :param loss: non-reduced loss of size N x C x H x W
        :param optimizer:
        :return: weight, channelwise loss, channelwise weighted loss
        """
        return lyd.rescale_last_layer_grad(self.mt_heads, loss, optimizer)

    def forward(self, x, external=None):
        x0 = x[:, [0]]
        x1 = x[:, [1]]
        x2 = x[:, [2]]
        if external is not None:
            x0 = torch.cat((x0, external), 1)
            x1 = torch.cat((x1, external), 1)
            x2 = torch.cat((x2, external), 1)

        o0 = self.unet_shared.forward(x0)
        o1 = self.unet_shared.forward(x1)
        o2 = self.unet_shared.forward(x2)

        o = torch.cat((o0, o1, o2), 1)
        o = self.unet_union.forward(o)

        o_head = []
        for i in range(self.ch_out):
            o_head.append(self.mt_heads[i].forward(o))
        o = torch.cat(o_head, 1)

        """Apply the final non-linearities"""
        if self._use_last_nl:
            o = self.apply_nonlin(o)

        return o


class MLTHeads(nn.Module):
    def __init__(self, in_channels, activation=nn.ReLU(), last_kernel=1, norm=None, norm_groups=None, padding=True):
        super().__init__()
        self.norm = norm
        self.norm_groups = norm_groups
        groups_1 = min(in_channels, self.norm_groups)
        groups_2 = min(1, self.norm_groups)
        padding = padding

        self.core = self._make_core(in_channels, groups_1, groups_2, activation, padding, norm)
        self.out_conv = nn.Conv2d(in_channels, 1, kernel_size=last_kernel, padding=False)

    def forward(self, x):
        o = self.core.forward(x)
        o = self.out_conv.forward(o)

        return o

    @staticmethod
    def _make_core(in_channels, groups_1, groups_2, activation, padding, norm):
        if norm == 'GroupNorm':
            return nn.Sequential(nn.GroupNorm(groups_1, in_channels),
                                 nn.Conv2d(in_channels, in_channels,
                                           kernel_size=3, padding=padding),
                                 activation,
                                 # nn.GroupNorm(groups_2, in_channels)
                                 )
        elif norm is None:
            return nn.Sequential(nn.Conv2d(in_channels, in_channels,
                                           kernel_size=3, padding=padding),
                                 activation)
        else:
            raise NotImplementedError


class DoubleMUNetSeperateBG(SimpleSMLMNet):
    def __init__(self, ch_in, ch_out, depth=3, initial_features=64, recpt_bg=16, inter_features=64, depth_bg=2,
                 initial_features_bg=16, activation=nn.ReLU(), use_last_nl=True, norm=None,  norm_groups=None,
                 norm_bg=None, norm_bg_groups=None):
        super().__init__(ch_in=ch_in, ch_out=5, depth=depth, initial_features=initial_features,
                         inter_features=inter_features, activation=activation,
                         use_last_nl=use_last_nl, norm=norm, norm_groups=norm_groups)

        self.bg_net = UNet2d(ch_in, 1, depth=depth_bg, pad_convs=True, initial_features=initial_features_bg,
                             activation=activation, norm=norm_bg, norm_groups=norm_bg_groups)

        self.bg_nl = torch.tanh
        self.bg_recpt = recpt_bg

    @staticmethod
    def parse(param):
        activation = eval(param['HyperParameter']['arch_param']['activation'])
        return DoubleMUNetSeperateBG(
            ch_in=param['HyperParameter']['channels_in'],
            ch_out=param['HyperParameter']['channels_out'],
            depth=param['HyperParameter']['arch_param']['depth'],
            initial_features=param['HyperParameter']['arch_param']['initial_features'],
            recpt_bg=param['HyperParameter']['arch_param']['recpt_bg'],
            depth_bg=param['HyperParameter']['arch_param']['depth_bg'],
            initial_features_bg=param['HyperParameter']['arch_param']['initial_features_bg'],
            inter_features=param['HyperParameter']['arch_param']['inter_features'],
            activation=activation,
            use_last_nl=param['HyperParameter']['arch_param']['use_last_nl'],
            norm=param['HyperParameter']['arch_param']['norm'],
            norm_groups=param['HyperParameter']['arch_param']['norm_groups'],
            norm_bg=param['HyperParameter']['arch_param']['norm_bg'],
            norm_bg_groups=param['HyperParameter']['arch_param']['norm_bg_groups']
        )

    def forward(self, x):
        """

        :param x:
        :return:
        """
        """
        During training, limit the 
        """
        if self.training:
            bg_out = torch.zeros_like(x[:, [0]])
            assert x.size(-1) % self.bg_recpt == 0
            assert x.size(-2) % self.bg_recpt == 0
            n_x = x.size(-2) // self.bg_recpt
            n_y = x.size(-1) // self.bg_recpt
            for i in range(n_x):
                for j in range(n_y):
                    ii = slice(i * self.bg_recpt, (i + 1) * self.bg_recpt)
                    jj = slice(j * self.bg_recpt, (j + 1) * self.bg_recpt)
                    bg_out[:, :, ii, jj] = self.bg_net.forward(x[:, :, ii, jj])
        else:
            bg_out = self.bg_net.forward(x)

        out = super().forward(x, bg_out.detach())
        return torch.cat((out, bg_out), 1)


class BGNet(nn.Module):
    def __init__(self, ch_in, ch_out, depth_bg=2, initial_features_bg=16, activation=nn.ReLU(), norm=None):
        super().__init__()
        self.ch_out = ch_out  # pseudo channels for easier trainig
        self.net = UNet2d(in_channels=ch_in,
                          out_channels=1,
                          depth=depth_bg,
                          initial_features=initial_features_bg,
                          pad_convs=True,
                          activation=activation,
                          norm=norm)

    @staticmethod
    def parse(param):
        activation = eval(param['HyperParameter']['arch_param']['activation'])
        return BGNet(
            ch_in=param['HyperParameter']['channels_in'],
            ch_out=param['HyperParameter']['channels_out'],
            depth_bg=param['HyperParameter']['arch_param']['depth_bg'],
            initial_features_bg=param['HyperParameter']['arch_param']['initial_features_bg'],
            activation=activation,
            norm=param['HyperParameter']['arch_param']['norm']
        )

    def apply_pnl(self, x):
        return x

    def forward(self, x):
        o = self.net.forward(x)
        if self.ch_out >= 2:
            o = torch.cat((torch.zeros((o.size(0), self.ch_out - 1, o.size(-2), o.size(-1))).to(o.device), o), 1)

        return o


if __name__ == '__main__':
    model = DoubleMUNetSeperateBG(3, 6, depth=2, depth_bg=2, initial_features_bg=32, recpt_bg=16, use_last_nl=False,
                                  norm='GroupNorm')
    x = torch.rand((10, 3, 32, 32))
    y = torch.rand((10, 6, 32, 32))
    optimiser = torch.optim.Adam(model.parameters(), lr=0.0001)
    criterion = torch.nn.MSELoss(reduction='none')
    model.train()
    out = model.forward(x)
    loss = criterion(out, y)
    optimiser.zero_grad()

    print('Done')