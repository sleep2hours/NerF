from pyexpat import model
from numpy import gradient
from sklearn.utils import shuffle
from yaml import parse
from lego_loder import MyDataset
from torch.utils.data import DataLoader
import torch
from Nerf import *
import configargparse

parser = configargparse.ArgumentParser()
parser.add_argument('--half_res', type=bool, default=False,
                    help='resolution of 400')
parser.add_argument('--is_train', type=bool,
                    default=True, help='train or test')
parser.add_argument('--epoch', type=int, default=150000, help='total epochs')
parser.add_argument('--lr', type=float, default=5e-4,
                    help='initial learning rate')
parser.add_argument('--cpts_num', type=int, default=10,
                    help='numbers of coarse sample points')
parser.add_argument('--fpts_num', type=int, default=128,
                    help='addtional numbers of fine sample points')
parser.add_argument('--near', type=float, default=2., help='z of near plane')
parser.add_argument('--far', type=float, default=6., help='z of far plane')
parser.add_argument('--xins', type=int, default=60,
                    help='dimensions of gama(x)')
parser.add_argument('--dins', type=int, default=36,
                    help='dimensions of gama(d)')
parser.add_argument('--W', type=int, default=256,
                    help='dimensions of each mlp')
parser.add_argument('--mlps', type=int, default=8, help='layers of mlp')
args = parser.parse_args()

if not torch.cuda.is_available():
    print("CUDA not available.")
    exit(-1)

def train():
    train_data = MyDataset(
        root_dir='./lego/', half_res=args.half_res, is_train=args.is_train)

    train_loder = DataLoader(train_data, batch_size=8,
                             shuffle=True, num_workers=4)
    H, W = 800, 800
    focal = W/(2*torch.tan(0.5*train_data.cam_fov))
    K = torch.tensor([[focal, 0, W//2], [0, focal, H//2], [0, 0, 1]])
    model_coarse=Nerf(args)
    model_fine=Nerf(args)
    grad_vars=list(model_coarse.parameters())
    grad_vars+=list(model_fine.parameters())
    optimizer = torch.optim.Adam(
        params=grad_vars, lr=args.lr)
    for i in range(args.epoch):
        for i, (img, tfs) in enumerate(train_loder):
            """
            img:B*3*H*W
            tfs:B*4*4
            """
            # optimizer.zero_grad()
            img=img.cuda()
            tfs=tfs.cuda()
            rays_o, rays_dir = raysGet(K, tfs)
            coarse_sample = randomraysSample(rays_o, rays_dir, args.cpts_num, args.near, args.far)
            # view(coarse_sample,rays_o,rays_dir)
            rays_dir=rays_dir[:,:,:,None,:].expand(coarse_sample.size())
            coarse_sigma, coarse_RGB=model_coarse(coarse_sample,rays_dir)
            print(coarse_sample.shape)
            print(coarse_RGB.shape)
            break
            
           
            # coarse_render = colRender(coarse_sample, coarse_sigma, coarse_RGB)
            # fine_sample = invSample(coarse_sample, coarse_sigma, args.fpts_num)
            # fine_sigma, fine_RGB = model_fine(fine_sample)
            # # TODO:concat concat fine_render and coarse_render
            # fine_render = cloRender(fine_sample, fine_sigma, fine_RGB)
            # loss = img2mse(fine_render, img)+img2mse(coarse_render, img)
            # loss.backward()
            # optimizer.step()
            # new_lr = args.lr*(0.1**(i/args.epoch))
            # for param in optimizer.param_groups:
            #     param['lr'] = new_lr

if __name__=='__main__':
    train()