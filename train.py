import torch
from torch_geometric.data import DataLoader
from dataset import MoleculeDataset
from tqdm import tqdm
import numpy as np
from torch.utils.tensorboard import SummaryWriter   
from utils import (count_parameters, gvae_loss, 
        slice_edge_type_from_edge_feats, slice_atom_type_from_node_feats)
from gvae import GVAE
from config import DEVICE as device

# Initial TensorBoard
writer = SummaryWriter()

# Load data
train_dataset = MoleculeDataset(root="data/", filename="HIV_train_oversampled.csv")[:10000]
test_dataset = MoleculeDataset(root="data/", filename="HIV_test.csv", test=True)[:1000]
train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
test_loader = DataLoader(test_dataset, batch_size=32, shuffle=True)

# Load model
model = GVAE(feature_size=train_dataset[0].x.shape[1])
model = model.to(device)
print("Model parameters: ", count_parameters(model))

# Define loss and optimizer
loss_fn = gvae_loss
optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
kl_beta = 0.5

# Train function
def run_one_epoch(data_loader, type, epoch, kl_beta):
    # Store per batch loss and accuracy 
    all_losses = []
    all_kldivs = []

    # Iterate over data loader
    for _, batch in enumerate(tqdm(data_loader)):
        # Some of the data points have invalid adjacency matrices 
        try:
            # Use GPU
            batch.to(device)  
            # Reset gradients
            optimizer.zero_grad() 
            # Call model
            triu_logits, node_logits, mu, logvar = model(batch.x.float(), 
                                                        batch.edge_attr.float(),
                                                        batch.edge_index, 
                                                        batch.batch) 
            # Calculate loss and backpropagate
            edge_targets = slice_edge_type_from_edge_feats(batch.edge_attr.float())
            node_targets = slice_atom_type_from_node_feats(batch.x.float(), as_index=True)
            loss, kl_div = loss_fn(triu_logits, node_logits,
                                   batch.edge_index, edge_targets, 
                                   node_targets, mu, logvar, 
                                   batch.batch, kl_beta)
            if type == "Train":
                loss.backward()  
                optimizer.step() 
            # Store loss and metrics
            all_losses.append(loss.detach().cpu().numpy())
            #all_accs.append(acc)
            all_kldivs.append(kl_div.detach().cpu().numpy())
        except IndexError as error:
            # For a few graphs the edge information is not correct
            # Simply skip the batch containing those
            print("Error: ", error)
    
    # Perform sampling
    if type == "Test":
        generated_mols = model.sample_mols(device=device, num=10000)
        print(f"Generated {generated_mols} molecules.")
        writer.add_scalar('Sampled molecules', float(generated_mols), epoch)

    print(f"{type} epoch {epoch} loss: ", np.array(all_losses).mean())
    #Write loss for epoch
    writer.add_scalar('Epoch Loss',float(np.array(all_losses).mean()),epoch)
    writer.add_scalar('KL Divergence',float(np.array(all_kldivs).mean()),epoch)

# Run training
for epoch in range(5): 
        model.train()
        run_one_epoch(train_loader, type="Train", epoch=epoch, kl_beta=kl_beta)
        if epoch % 5 == 0:
            print("Start test epoch...")
            model.eval()
            run_one_epoch(test_loader, type="Test", epoch=epoch, kl_beta=kl_beta)