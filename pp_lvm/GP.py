# AUTOGENERATED! DO NOT EDIT! File to edit: 03_GP.ipynb (unless otherwise specified).

__all__ = ['device', 'add_jitter_covar', 'get_covariance_matrix_from_RBFkernel',
           'get_covariance_matrix_from_RBFkernel_new', 'plot_predictions', 'ExactGPModelLayer', 'Model_X',
           'inference_X']

# Cell
import numpy as np
import matplotlib.pyplot as plt

import torch
import torch.distributions as dist
import torch.nn as nn
import torch.nn.functional as F
import gpytorch

# Cell
from .simulations import TrueParameters, simulate_data, transform_x

# Cell
device = 'cuda' if torch.cuda.is_available() else 'cpu'

# Cell
def add_jitter_covar(M, eps=1e-6):
    identity_matrix = torch.eye(M.shape[-1]).to(M.device)
    M = M + eps * identity_matrix
    return M

# Cell
def get_covariance_matrix_from_RBFkernel(M, lengthscale=20, eps=1e-6, device=device):
    x1 = M.unsqueeze(-2).div(lengthscale)
    x2 = M.unsqueeze(-1).div(lengthscale)
    K = torch.pow(x1-x2, 2).div(-2).exp()
    # Adding jitter for numerical stability
    K = add_jitter_covar(K, eps=eps)
#     K += 1e-6*torch.eye(M.shape[-1]).to(device)
    return K

def get_covariance_matrix_from_RBFkernel_new(M1, M2, lengthscale=20, eps=1e-6, device=device):
    assert (M1.shape[:-1] == M2.shape[:-1])
    x1 = M1.unsqueeze(-1).div(lengthscale)
    x2 = M2.unsqueeze(-2).div(lengthscale)
    K = torch.pow(x1-x2, 2).div(-2).exp()
    # Adding jitter for numerical stability
    if (eps > 0) and (M1.shape[-1] == M2.shape[-1]):
        K = add_jitter_covar(K, eps=eps)
    return K

# Cell
def plot_predictions(train_x, train_y, test_x, observed_pred, num_plots=1):
    """
    train_x: shape=(BS,S)
    train_y: shape=(BS,S)
    test_x: shape=(BS,S')
    observed_pred: shape=(BS,S')
    """
    train_x = Model_X.reshape_T(train_x, train_x.shape).cpu()
    train_y = Model_X.reshape_X(train_y, train_x.shape).cpu()
    test_x = Model_X.reshape_T(test_x, test_x.shape).cpu()

    with torch.no_grad():
        for s in range(num_plots):
            # Initialize plot
            f, ax = plt.subplots(1, 1, figsize=(8, 6))
            # Get upper and lower confidence bounds
            lower, upper = observed_pred.confidence_region()
            lower = lower.cpu()
            upper = upper.cpu()
            # Plot training data as black stars
            ax.plot(train_x.numpy()[s].flatten(), train_y.detach().numpy()[s], 'k*')
            # Plot predictive means as blue line
            ax.plot(test_x.numpy()[s].flatten(), observed_pred.mean.cpu().numpy()[s], 'b')

            ax.plot(test_x[s].flatten().numpy(), transform_x(test_x[s].flatten()).numpy(), 'r')
            # Shade between the lower and upper confidence bounds
            ax.fill_between(test_x[s].flatten().numpy(), lower[s].numpy(), upper[s].numpy(), alpha=0.5)
            ax.set_xlim([train_x[s].min()-50, train_x[s].max()+50])
            ax.set_ylim([-1.2, 1.2])
            ax.legend(['Observed Data', 'Mean', 'True', 'Confidence'])
    plt.show()

# Cell
class ExactGPModelLayer(gpytorch.models.ExactGP):
    def __init__(self, train_x, train_y, likelihood, BS):
        super().__init__(train_x, train_y, likelihood)
        self.mean_module = gpytorch.means.ConstantMean(batch_shape=torch.Size([BS]))
        self.covar_module = gpytorch.kernels.ScaleKernel(
            gpytorch.kernels.RBFKernel(batch_shape=torch.Size([BS]), lengthscale_prior=gpytorch.priors.GammaPrior(250., 1.)),
            # gpytorch.kernels.RBFKernel(batch_shape=torch.Size([BS])),
            # gpytorch.kernels.RBFKernel(batch_shape=torch.Size([BS]), lengthscale_prior=gpytorch.priors.SmoothedBoxPrior(20, 100)),
            batch_shape=torch.Size([BS])
        )

    def forward(self, x):
        mean_x = self.mean_module(x)
        covar_x = self.covar_module(x)
        # import pdb; pdb.set_trace()
        return gpytorch.distributions.MultivariateNormal(mean_x, covar_x)

# Cell
class Model_X:
    def __init__(self, T, X, device=device):
        self.Tshape = T.shape
        self.Xshape = X.shape
        BS = T.shape[0]

        train_x = self.reshape_T(T, self.Tshape)
        train_y = self.reshape_X(X, self.Tshape)
        # initialize likelihood and model
        self.likelihood = gpytorch.likelihoods.GaussianLikelihood(noise_prior=gpytorch.priors.NormalPrior(.01,1),
                                                                  batch_shape=torch.Size([BS])).to(device)
        self.model = ExactGPModelLayer(train_x, train_y, self.likelihood, BS).to(device)

    @staticmethod
    def reshape_T(T, Tshape):
        train_x = T.view(*Tshape, 1)
        return train_x

    @staticmethod
    def reshape_X(X, Tshape):
        train_y = X.view(Tshape)
        return train_y

    def fit(self, T, X, training_iter=1000, lr=0.1, verbose=True):
        train_x, train_y = self.reshape_T(T, self.Tshape), self.reshape_X(X, self.Tshape)

        self.model.train()
        self.likelihood.train()

        optimizer = torch.optim.Adam([
            {'params': self.model.parameters()},  # Includes GaussianLikelihood parameters
        ], lr=lr)

        mll = gpytorch.mlls.ExactMarginalLogLikelihood(self.likelihood, self.model)

        for i in range(training_iter):
            # Zero gradients from previous iteration
            optimizer.zero_grad()
            # Output from model
            output = self.model(train_x)
            # Calc loss and backprop gradients
            loss = -mll(output, train_y).sum()
            loss.backward(retain_graph=True)
            if verbose:
                if i % (training_iter//10) ==0 :
                    print(f'Iter {i + 1}/{training_iter} - Loss: {loss.item()}, \
                    mean lengthscale: {self.model.covar_module.base_kernel.lengthscale.mean().item()}')
            optimizer.step()

        self.model.eval()
        self.likelihood.eval()

    def get_posterior(self, test_x):
        """
        test_x: shape: (BS, S, 1), BS: should be the same batch size as the training data or 1 (will broadcast)

        Output:

        """
        # Get into evaluation (predictive posterior) mode
        self.model.eval()
        self.likelihood.eval()

        with gpytorch.settings.fast_pred_var():
            observed_pred = self.likelihood(self.model(test_x))

        return observed_pred

    def predict(self, test_x):
        """
        test_x: shape: (BS, S, 1), BS: should be the same batch size as the training data or 1 (will broadcast)
        """
        # Get into evaluation (predictive posterior) mode
        self.model.eval()
        self.likelihood.eval()

        # Test points are regularly spaced along [0,1]
        # Make predictions by feeding model through likelihood
        with torch.no_grad(), gpytorch.settings.fast_pred_var():
            # test_x = torch.linspace(0, T.max(), 100).view(1,100,1).expand(10,100,1)
            observed_pred = self.likelihood(self.model(test_x))

        return observed_pred

# Cell
def inference_X(T, X, _model_x=None, training_iter=2000, lr=0.1, device=device, verbose=True):
    """
    T: shape=(BS,S)
    X: shape=(BS,S)
    """
    if _model_x is None:
        _model_x = Model_X(T, X, device=device)
        _model_x.fit(T, X, training_iter=training_iter, lr=lr, verbose=verbose)
    return _model_x