import torch
from torch import nn
import torch.nn.functional as F
import numpy as np
from cmath import pi
import matplotlib.pyplot as plt
from matplotlib import projections
import numpy as np

def posEmbed(x: torch.tensor, L: int) -> torch.tensor: 
    result = []
    B, N = x.shape[0], x.shape[1]
    freq = 2.**torch.linspace(0, L-1, L)
    func = [torch.cos, torch.sin]
    for fre in freq:
        for f in func:
            result.append(f(fre*x))
    return torch.cat(result, dim=-1)

class Nerf(nn.Module):
    def __init__(self, args):
        super().__init__()
        self.xins = args.xins  
        self.dins = args.dins 
        self.W = args.W 
        self.mlps = args.mlps

        assert self.mlps % 2 == 0
        self.linear1 = nn.ModuleList([nn.Linear(
            self.xins, self.W)]+[nn.Linear(self.W, self.W) for i in range(self.mlps // 2)])
        self.linear2 = nn.ModuleList([nn.Linear(
            self.W+self.xins, self.W)]+[nn.Linear(self.W, self.W) for i in range(self.mlps //2)])
        self.linear_sigma = nn.Linear(self.W, 1)
        self.linear_rgb = nn.ModuleList([nn.Linear(self.W+self.dins, self.W//2), nn.Linear(self.W//2, 3)])

    def forward(self, x, d): #x:B*R*pts*3
        x = posEmbed(x, self.xins//6)   
        d = posEmbed(d, self.dins//6)
        gamax = x
        for l in self.linear1:
            x = l(x)
            x = F.relu(x, inplace=True)
        x = torch.cat((gamax, x), dim=-1)
        for l in self.linear2:
            x = l(x)
            x = F.relu(x, inplace=True)
        sigma = self.linear_sigma(x)
        sigma=F.relu(sigma).squeeze(-1)
        x = torch.cat([d, x], dim=-1)
        x = self.linear_rgb[0](x)
        x = F.relu(x, inplace=True)
        rgb = self.linear_rgb[1](x)
        rgb=F.relu(rgb)
        output = [sigma, rgb]
        return output


def raysGet(K,c2w):
    H=int(K[0][2])
    W=int(K[1][2])
    focal=float(K[0][0])
    x, y = torch.meshgrid(torch.linspace(0, W-1, W), torch.linspace(0, H-1, H))
    x, y = x.t(), y.t()
    cam_dir = torch.stack(((x-0.5*W)/focal, -(y-0.5*H) /focal, -torch.ones_like(x)), dim=-1).cuda()
    rays_dir = torch.matmul(c2w[:,None,None,:3, :3], cam_dir.unsqueeze(dim=-1)).squeeze(-1)
    rays_dist=torch.sqrt(torch.matmul(cam_dir[:,:,None,:],cam_dir[:,:,:,None])).squeeze(-1)
    rays_o = c2w[:,None,None,:3, -1].expand(rays_dir.size())
    """
    rays_o : B*H*W*3
    rays_dir : B*H*W*3
    rays_dist : H*W*1 
    """
    return rays_o, rays_dir,rays_dist


def randomraysSample(rays_o, rays_dir, rays_dist,pts_num, d_near, d_far):
    B,H, W, _ = rays_o.size()
    t_bound = torch.linspace(d_near, d_far, pts_num)
    t_val = torch.rand(B,H, W, pts_num)  
    t_val=torch.sort(t_val,dim=-1).values
    t = t_bound+t_val
    t=t.cuda()
    sample = rays_o[:,:,:,None,:]+t.unsqueeze(-1)*rays_dir.unsqueeze(-2)
    sample_d=t*rays_dist
    """
    sample:B*H*W*pts*3
    sample_d: B*H*W*pts
    """
    return sample,sample_d

def view(sample, rays_o, rays_dir,pt_fine=False):
    scale = torch.linspace(0, 3.5, 2).cuda()
    if not pt_fine:
        rays = rays_o[:,:,:,None,:]+scale.unsqueeze(-1)*rays_dir.unsqueeze(-2)
    else:
        rays=rays_o[:,:,None,:]+scale.unsqueeze(-1)*rays_dir[:,:,0,:].unsqueeze(-2)
    rays = rays.cpu().numpy()
    origin = rays_o.cpu().numpy()
    points = sample.cpu().detach().numpy()
    if not pt_fine:
        B, H,W, pts, _ = points.shape
    else:
        B,N,pts,_=points.shape
    assert (B%2==0 or B==1)
    fig = plt.figure('graph')
    ax = fig.add_subplot(111, projection='3d')
    ax.set_title('3D viewer')
    ax.set_xlabel('x')
    ax.set_ylabel('y')
    ax.set_zlabel('z')
    if not pt_fine:
        for i in range(0,B,2):
            for j in range(0,H,80):
                for k in range(0,W,100):
                    ax.plot(rays[i, j, k,:, 0], rays[i, j,k, :, 1], rays[i, j, k,:, 2], linewidth=1)
                    ax.scatter(points[i, j,k, :, 0], points[i, j,k, :, 1], points[i, j, k,:, 2],s=2)
            ax.scatter(origin[i,0,0, 0], origin[i,0,0, 1], origin[i,0,0,2],s=2)
    else:
        for i in range(0,B,2):
            for j in range(0,N,64):
                ax.scatter(points[i, j, :, 0], points[i, j, :, 1], points[i, j, :, 2],s=2)
                ax.plot(rays[i, j, :, 0], rays[i, j, :, 1], rays[i, j, :, 2], linewidth=1)
    plt.show()

def raysBatchify(sample,rays_ori,rays_dir,rays_dists,sample_d,img,batch_size=1024)->list:
    res_sample=[]
    res_ori=[]
    res_dirs=[]
    res_dists=[]
    res_d=[]
    res_img=[]
    B,H,W,pts,d=sample.size()
    sample=sample.reshape((B,H*W,pts,d))
    rays_ori=rays_ori.reshape((B,H*W,d))
    rays_dir=rays_dir.reshape((B,H*W,pts,d))
    rays_dists=rays_dists.unsqueeze(0).expand((B,H,W,1))
    rays_dists=rays_dists.reshape((B,H*W))
    sample_d=sample_d.reshape((B,H*W,pts))
    img=img.reshape((B,3,H*W))
    group_num=(H*W)//batch_size
    if not (H*W)%batch_size==0:
        group_num+=1
    for i in range(group_num):
        if H*W-i*batch_size<batch_size:
           res_sample.append(sample[:,i*batch_size:,:,:])
           res_ori.append(rays_ori[:,i*batch_size:,:])
           res_dirs.append(rays_dir[:,i*batch_size:,:,:])
           res_dists.append(rays_dists[:,i*batch_size:])
           res_d.append(sample_d[:,i*batch_size:,:])
           res_img.append(img[:,:,i*batch_size:])
           break 
        res_sample.append(sample[:,i*batch_size:(i+1)*batch_size,:,:])
        res_ori.append(rays_ori[:,i*batch_size:(i+1)*batch_size,:])
        res_dirs.append(rays_dir[:,i*batch_size:(i+1)*batch_size,:,:])
        res_dists.append(rays_dists[:,i*batch_size:(i+1)*batch_size])
        res_d.append(sample_d[:,i*batch_size:(i+1)*batch_size,:])
        res_img.append(img[:,:,i*batch_size:(i+1)*batch_size])
    return res_sample,res_ori,res_dirs,res_dists,res_d,res_img
    
def colRender(sample_dist,rays_dist,sigma, RGB):
    B,N,pts=sample_dist.size()
    diff=torch.cat([rays_dist.unsqueeze(-1),sample_dist],dim=-1)
    prob=-(sample_dist-diff[:,:,:-1])*sigma
    Ti=prob
    Ti=torch.cumsum(Ti,-1)
    Ti=torch.exp(Ti)
    prob=1-torch.exp(prob)
    weight=Ti*prob+1e-4
    Cr=RGB * weight[...,None]
    weight_sum=torch.sum(weight,dim=-1)
    weight=weight/weight_sum[...,None]
    """
    Cr：IB*RB*pts*3
    weight: IB*RB*pts
    """
    return Cr,weight

def invSample(PDF,pts_num,rays_o,rays_dirs,rays_dist,near,far,coarse_dist):
    IB,RB,pts=PDF.size()
    stride=(far-near)/pts
    CDF=torch.cumsum(PDF,-1)
    CDF=torch.cat([torch.zeros_like(CDF[:,:,:1]),CDF],dim=-1)
    sam=torch.rand(IB,RB,pts_num).cuda()
    below=torch.searchsorted(CDF,sam,right=True)-1
    t0=below*stride
    CDF=CDF.unsqueeze(-1).expand(list(CDF.shape)+[pts_num])
    PDF=PDF.unsqueeze(-1).expand(list(PDF.shape)+[pts_num])
    below=below.unsqueeze(-2)
    t=(sam.unsqueeze(-2)-torch.gather(CDF,-2,below))/torch.gather(PDF,-2,below)
    t=t.squeeze(-2)
    sample_t=t0+t
    coarse_scale=coarse_dist/rays_dist.unsqueeze(-1)
    sample_t=torch.cat([sample_t,coarse_scale],dim=-1)
    sample_t=torch.sort(sample_t,dim=-1).values
    rays_dir=rays_dirs[:,:,0,:]
    rays_dir=rays_dir.unsqueeze(-2).expand([IB,RB,pts+pts_num,3])
    sample= rays_o[:,:,None,:]+sample_t.unsqueeze(-1)*rays_dir
    sample_dist=sample_t*rays_dist.unsqueeze(-1)
    """
    sample: IB*RB*P*3
    sample_dist: IB*RB*P
    rays_dir: IB*RB*P*3
    """
    return sample,sample_dist,rays_dir

