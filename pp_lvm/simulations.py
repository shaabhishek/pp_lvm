# AUTOGENERATED! DO NOT EDIT! File to edit: 01_simulations.ipynb (unless otherwise specified).

__all__ = ['device', 'TrueParameters', 'transform_x', 'link_gamma', 'sample_using_logits', 'get_time_from_intervals',
           'simulate_XZI_seq', 'simulate_XZI', 'simulate_H', 'simulate_Y', 'simulate_data', 'visualize']

# Cell
import numpy as np
import matplotlib.pyplot as plt

import torch
import torch.distributions as dist
import torch.nn as nn
import torch.nn.functional as F

# Cell
device = 'cuda' if torch.cuda.is_available() else 'cpu'

# Cell
class TrueParameters:
    def __init__(self, S=50, N=10, device=device, B=3, H_dim=2, Y_dim=2, noise_X=1.0, noise_H=1.0):
        # Hyperparameters
        self.S,self.N = S,N

        # x
        self.noise_X = torch.tensor(noise_X, dtype=torch.float32).to(device)

        # z
        self.B = B
        self.P = (torch.rand((self.B,self.B)) + torch.eye(self.B,self.B)).to(device)
        self.logpi = torch.rand((1,self.B))
        self.Wx = torch.rand(self.B).to(device)

        # h
        self.H_dim = H_dim
        self.noise_H = torch.tensor(noise_H, dtype=torch.float32).to(device)
        self.mu_h = torch.randn(self.B, self.H_dim).to(device)
        self.sigma_h = torch.rand(self.B, self.H_dim).view(self.B, self.H_dim) * torch.randint(1,10, (1,), dtype=torch.float32)
        self.sigma_h = self.sigma_h.to(device)

        # i
        self.beta_a = torch.tensor([-np.log(4), 0.,0.]).to(device)
        self.beta_b = torch.tensor([0., 0.,0.]).to(device)

        # y
        self.Y_dim = Y_dim
        self.W_mu_y = torch.randn(self.H_dim, self.Y_dim).to(device)
        self.W_sigma_y = torch.rand(self.H_dim, self.Y_dim).to(device)


# Cell
transform_x = lambda t: torch.sin(t/200)*.7 - .1

# Cell
def link_gamma(xn, zn, Params):
    device = xn.device
    data = torch.tensor([1., xn, zn]).to(device)
    a,b = (torch.dot(Params.beta_a, data).mul(-1).exp(), torch.dot(Params.beta_b, data).mul(-1).exp())
    # print(a,b)
    return a,b

# Cell
def sample_using_logits(logits):
    return dist.Categorical(logits=logits).sample()

# Cell
def get_time_from_intervals(I):
    last_dim_size = I.shape[-1]
    I = F.pad(I, (1,0)) #pads the last dimension with width=1 on the left and width=0 on the right. Value of padding=0
    I = I.cumsum(dim=-1)
    # Note: new I has one element extra than initial I on the final dimension. This cuts that one last element in a general way
    I = torch.stack([torch.select(I, I.dim()-1, i) for i in range(last_dim_size)], dim=-1)
    return I

# Cell
def simulate_XZI_seq(Params, device=device, noise_X=1.):
    t = torch.tensor([0.]).to(device)
    X_s = [transform_x(t)]
    Z_s = [sample_using_logits(Params.Wx*X_s[0])]
    I_s = [dist.Gamma(*link_gamma(X_s[0], Z_s[0], Params)).sample()]

    for n in range(1, Params.N):
        t += I_s[-1]
        X_s.append(transform_x(t) + torch.randn((1,), device=device)*Params.noise_X) #uses current t which is a function of all I_{t'}, t' < t
        Z_s.append(sample_using_logits(Params.Wx*X_s[-1] + Params.P[Z_s[-1]])) #X_{t} and Z_{t-1}
        I_s.append(dist.Gamma(*link_gamma(X_s[-1], Z_s[-1], Params)).sample()) #X_{t} and Z_{t}

    X_s, Z_s, I_s = torch.tensor(X_s).to(device), torch.tensor(Z_s).to(device), torch.tensor(I_s).to(device)
    return X_s, Z_s, I_s

def simulate_XZI(Params):
    X, Z, I = [], [], []
    noise_X = Params.noise_X
    for s in range(Params.S):
        X_s, Z_s, I_s = simulate_XZI_seq(Params, noise_X=noise_X)
        X.append(X_s)
        Z.append(Z_s)
        I.append(I_s)

    return torch.stack(X, dim=0), torch.stack(Z, dim=0), torch.stack(I, dim=0)



# Cell
def simulate_H(Z,Params):
    H = []
    for s in range(Params.S):
        Z_s = Z[s]
        H_s = torch.stack([dist.Normal(Params.mu_h[Z_s[n]], Params.sigma_h[Z_s[n]]*Params.noise_H ).sample() for n in range(Params.N)], dim=0)
        H.append(H_s)
    return torch.stack(H, dim=0) #shape: (S,T,H_dim)

# Cell
def simulate_Y(H, Params):
    mu, sigma = torch.matmul(H, Params.W_mu_y), torch.matmul(H, Params.W_sigma_y)
    Y = dist.Normal(mu, sigma).sample()
    return Y

# Cell
def simulate_data(Params):
    X, Z, I = simulate_XZI(Params)
    T = get_time_from_intervals(I)
    H = simulate_H(Z, Params)
    Y = simulate_Y(H, Params)
    return I,Y,T,X,Z,H

# Cell
def visualize(Params, X,T,I,H=None):
    fig, ax = plt.subplots(3,2, figsize=(8,8))

    s = 0
    ax[0,0].plot(torch.linspace(1e-6,T[s,-1],100), transform_x(torch.linspace(1e-6,T[s,-1],100)))
    ax[0,0].scatter(T[s].cpu(), X[s].cpu())
    ax[0,0].set_title(f"Latent state $x(t)$ ({s+1}th Seq)")

    im = ax[0,1].imshow(Params.P.cpu())
    fig.colorbar(im, ax=ax[0,1])
    ax[0,1].set_title("Base transition logits")

    for _s in range(min(5, Params.S)):
        ax[1,0].scatter(T[_s].cpu(), torch.zeros_like(T[_s].cpu())+_s)
    ax[1,0].set_title("Event Times (5 indpt sequences)")

    ax[1,1].hist(I[s].cpu().numpy(), bins=20)
    ax[1,1].set_title(f"Histogram of Interval Times ({s+1}th sequence)")

    if H is not None:
        ax[2,0].scatter(T[s].cpu(), H[s,:,0].cpu())
        try:
            ax[2,1].scatter(T[s].cpu(), H[s,:,1].cpu())
        except:
            pass