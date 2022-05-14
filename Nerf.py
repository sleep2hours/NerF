from re import X
import torch
from torch import nn
import torch.nn.functional as F
import numpy as np
from cmath import pi


def posEmbed(x: torch.tensor, L: int) -> torch.tensor:  # x:N*L*3
    '''
    func = [torch.sin, torch.cos]
    freq = 2**torch.linspace(0, L-1, L)*pi
    B, N, S = x.size()
    freq_pos = torch.zeros(B, N, S*2*L)
    for i in range(B):
        for j in range(N):
            for k in range(S):
                freq_pos[i, j, k*2*L:(k+1)*2*L] = torch.tensor([f(p)
                                                                for p in x[i, j, k]*freq for f in func])
    return freq_pos
    '''
    result = []
    B, N = x.shape[0], x.shape[1]
    freq = 2.**torch.linspace(0, L-1, L)
    func = [torch.cos, torch.sin]
    for fre in freq:
        for f in func:
            result.append(f(fre*x.unsqueeze(-1)))
    return torch.cat(result, dim=-1).view(B, N, -1)


def mlpMaker(in_cha, out_cha, act_fun=nn.ReLU(), norm=None):
    modules = [nn.Linear(in_cha, out_cha)]
    if norm is not None:
        modules.append(norm(out_cha))
    if act_fun is not None:
        modules.append(act_fun)
    return modules


class Nerf(nn.Module):
    def __init__(self, xins=60, dins=24, W=256, mlp_num=8):
        super().__init__()
        self.xins = xins  # dimensions of gama(x)
        self.dins = dins  # dimensions of gama(d)
        self.W = W  # dimessions of MLP
        self.mlp_num = mlp_num

        assert self.mlp_num % 2 == 0
        self.linear1 = nn.ModuleList([nn.Linear(
            self.xins, self.W)]+[nn.Linear(self.W, self.W) for i in range(self.mlp_num % 2-1)])
        self.linear2 = nn.Linear(self.W, self.W)
        self.linear3 = nn.ModuleList([nn.Linear(
            self.W+self.xins, self.W)]+[nn.Linear(self.W, self.W) for i in range(self.mlp_num % 2-1)])
        self.linear_sigma = nn.Linear(self.W, 1)
        self.linear_rgb = nn.ModuleList(
            [nn.Linear(self.W+self.dins, self.W//2), nn.Linear(self.W//2, 3)])

    def forward(self, x, d):
        x = posEmbed(x, self.xins//6)
        d = posEmbed(d, self.dins//4)
        gamax = x
        for l in self.linear1:
            x = l(x)
            x = F.relu(x, inplace=True)

        x = self.linear2(x)
        x = torch.cat((gamax, x), dim=-1)
        for l in self.linear3:
            x = l(x)
            x = F.relu(x, inplace=True)
        sigma = self.linear_sigma(x)
        x = torch.cat([d, x], dim=-1)
        x = self.linear_rgb[0](x)
        x = F.relu(x, inplace=True)
        rgb = self.linear_rgb[1](x)
        output = [sigma, rgb]
        return output


def raysGet(H, W, focal, c2w):
    x, y = torch.meshgrid(torch.linspace(0, W-1, W), torch.linspace(0, H-1, H))
    x, y = x.t(), y.t()
    car_dir = torch.stack(((x-0.5*W)/focal, -(y-0.5*H) /
                          focal, -torch.ones_like(x)), dim=-1)
    rays_dir = torch.matmul(c2w[:3, :3], car_dir.unsqueeze(dim=-1)).squeeze(-1)

    rays_o = c2w[:3, -1].expand(rays_dir.size())
    return rays_o, rays_dir


def randomraysSample(rays_o, rays_dir, pts_num, d_near, d_far):
    H, W, _ = rays_o.size()
    t_bound = torch.linspace(d_near, d_far, pts_num)
    t_val = torch.rand(H, W, pts_num)
    t = t_bound+t_val
    sample = rays_o.unsqueeze(-2)+t.unsqueeze(-1)*rays_dir.unsqueeze(-2)
    return sample
