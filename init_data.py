import numpy as np
import torch
import random
from sklearn.preprocessing import MinMaxScaler
import numpy as np
import pandas as pd
import copy as cp
from rdkit import Chem
from rdkit.Chem import AllChem

random.seed(777)
np.random.seed(777)

def inchi_to_smiles(inchi_list):
    """
    Convert a list of InChI strings to a list of canonical SMILES strings.

    Args:
    inchi_list (list): A list of InChI strings.

    Returns:
    list: A list of canonical SMILES strings.
    """
    smiles_list = []
    for inchi in inchi_list:
        mol = Chem.MolFromInchi(inchi)
        if mol:
            smiles = Chem.MolToSmiles(mol)
            smiles_list.append(smiles)
        else:
            smiles_list.append(None)  # Append None for invalid InChI strings
    return smiles_list


class FingerprintGenerator:
    def __init__(self, nBits=512, radius=2):
        self.nBits = nBits
        self.radius = radius

    def featurize(self, smiles_list):
        fingerprints = []
        for smiles in smiles_list:
            if not isinstance(smiles, str):
                fingerprints.append(np.ones(self.nBits))
            else:
                mol = Chem.MolFromSmiles(smiles)
                if mol is not None:
                    fp = AllChem.GetMorganFingerprintAsBitVect(
                        mol, self.radius, nBits=self.nBits
                    )
                    fp_array = np.array(
                        list(fp.ToBitString()), dtype=int
                    )  # Convert to NumPy array
                    fingerprints.append(fp_array)
                else:
                    print(f"Could not generate a molecule from SMILES: {smiles}")
                    fingerprints.append(np.array([None]))

        return np.array(fingerprints)
    


def convert2pytorch(X, y):
    X = torch.from_numpy(X).float()
    y = torch.from_numpy(y).float().reshape(-1, 1)
    return X, y


def check_entries(array_of_arrays):
    """
    Check if the entries of the arrays are between 0 and 1.
    Needed for for the datasets.py script.
    """

    for array in array_of_arrays:
        for item in array:
            if item < 0 or item > 1:
                return False
    return True


class directaryl:
    def __init__(self):
        # direct arylation reaction
        self.ECFP_size = 512
        self.radius = 2
        self.ftzr = FingerprintGenerator(nBits=self.ECFP_size, radius=self.radius)
        dataset_url = "https://raw.githubusercontent.com/doyle-lab-ucla/edboplus/main/examples/publication/BMS_yield_cost/data/PCI_PMI_cost_full.csv"
        self.data = pd.read_csv(dataset_url)
        self.data = self.data.sample(frac=1).reset_index(drop=True)
        # create a copy of the data
        data_copy = self.data.copy()
        # remove the Yield column from the copy
        data_copy.drop("Yield", axis=1, inplace=True)
        # check for duplicates
        duplicates = data_copy.duplicated().any()
        if duplicates:
            print("There are duplicates in the dataset.")
            exit()

        self.data["Base_SMILES"] = inchi_to_smiles(self.data["Base_inchi"].values)
        self.data["Ligand_SMILES"] = inchi_to_smiles(self.data["Ligand_inchi"].values)
        self.data["Solvent_SMILES"] = inchi_to_smiles(self.data["Solvent_inchi"].values)
        col_0_base = self.ftzr.featurize(self.data["Base_SMILES"])
        col_1_ligand = self.ftzr.featurize(self.data["Ligand_SMILES"])
        col_2_solvent = self.ftzr.featurize(self.data["Solvent_SMILES"])
        col_3_concentration = self.data["Concentration"].to_numpy().reshape(-1, 1)
        col_4_temperature = self.data["Temp_C"].to_numpy().reshape(-1, 1)
        self.X = np.concatenate(
            [
                col_0_base,
                col_1_ligand,
                col_2_solvent,
                col_3_concentration,
                col_4_temperature,
            ],
            axis=1,
        )
        self.experiments = np.concatenate(
            [
                self.data["Base_SMILES"].to_numpy().reshape(-1, 1),
                self.data["Ligand_SMILES"].to_numpy().reshape(-1, 1),
                self.data["Solvent_SMILES"].to_numpy().reshape(-1, 1),
                self.data["Concentration"].to_numpy().reshape(-1, 1),
                self.data["Temp_C"].to_numpy().reshape(-1, 1),
                self.data["Yield"].to_numpy().reshape(-1, 1),
            ],
            axis=1,
        )

        self.y = self.data["Yield"].to_numpy()
        self.all_ligands = self.data["Ligand_SMILES"].to_numpy()
        self.all_bases = self.data["Base_SMILES"].to_numpy()
        self.all_solvents = self.data["Solvent_SMILES"].to_numpy()
        unique_bases = np.unique(self.data["Base_SMILES"])
        unique_ligands = np.unique(self.data["Ligand_SMILES"])
        unique_solvents = np.unique(self.data["Solvent_SMILES"])
        unique_concentrations = np.unique(self.data["Concentration"])
        unique_temperatures = np.unique(self.data["Temp_C"])

        max_yield_per_ligand = np.array(
            [
                max(self.data[self.data["Ligand_SMILES"] == unique_ligand]["Yield"])
                for unique_ligand in unique_ligands
            ]
        )

        self.worst_ligand = unique_ligands[np.argmin(max_yield_per_ligand)]
        self.best_ligand = unique_ligands[np.argmax(max_yield_per_ligand)]

        self.where_worst_ligand = np.array(
            self.data.index[self.data["Ligand_SMILES"] == self.worst_ligand].tolist()
        )

        self.feauture_labels = {
            "names": {
                "bases": unique_bases,
                "ligands": unique_ligands,
                "solvents": unique_solvents,
                "concentrations": unique_concentrations,
                "temperatures": unique_temperatures,
            },
            "ordered_smiles": {
                "bases": self.data["Base_SMILES"],
                "ligands": self.data["Ligand_SMILES"],
                "solvents": self.data["Solvent_SMILES"],
                "concentrations": self.data["Concentration"],
                "temperatures": self.data["Temp_C"],
            },
        }


class Evaluation_data:
    def __init__(
        self
    ):
        self.get_raw_dataset()

        rep_size = self.X.shape[1]
        self.bounds_norm = torch.tensor([[0] * rep_size, [1] * rep_size])
        self.bounds_norm = self.bounds_norm.to(dtype=torch.float32)

        if not check_entries(self.X):
            print("###############################################")
            print(
                "Entries of X are not between 0 and 1. Adding MinMaxScaler to the pipeline."
            )
            print("###############################################")

            self.scaler_X = MinMaxScaler()
            self.X = self.scaler_X.fit_transform(self.X)

    def get_raw_dataset(self):
        # https://github.com/doyle-lab-ucla/edboplus/blob/main/examples/publication/BMS_yield_cost/data/PCI_PMI_cost_full_update.csv

        BMS = directaryl()
        self.data = BMS.data
        self.experiments = BMS.experiments
        self.X, self.y = BMS.X, BMS.y

        self.all_ligands = BMS.all_ligands
        self.all_bases = BMS.all_bases
        self.all_solvents = BMS.all_solvents

        self.best_ligand = BMS.best_ligand
        self.worst_ligand = BMS.worst_ligand
        self.where_worst_ligand = BMS.where_worst_ligand
        self.feauture_labels = BMS.feauture_labels


    def get_init_holdout_data(self, SEED):
        random.seed(SEED)
        torch.manual_seed(SEED)
        np.random.seed(SEED)

        indices_init = self.where_worst_ligand[:200]
        exp_init = self.experiments[indices_init]
        indices_holdout = np.setdiff1d(np.arange(len(self.y)), indices_init)

        np.random.shuffle(indices_init)
        np.random.shuffle(indices_holdout)

        X_init, y_init = self.X[indices_init], self.y[indices_init]
        X_holdout, y_holdout = self.X[indices_holdout], self.y[indices_holdout]
        exp_holdout = self.experiments[indices_holdout]

        LIGANDS_INIT = self.all_ligands[indices_init]
        LIGANDS_HOLDOUT = self.all_ligands[indices_holdout]

        X_init, y_init = convert2pytorch(X_init, y_init)
        X_holdout, y_holdout = convert2pytorch(X_holdout, y_holdout)

        return (
            X_init,
            y_init,
            X_holdout,
            y_holdout,
            LIGANDS_INIT,
            LIGANDS_HOLDOUT,
            exp_init,
            exp_holdout,
        )

DATASET = Evaluation_data()
bounds_norm = DATASET.bounds_norm

(
    X_init,
    y_init,
    X_candidate,
    y_candidate, 
    LIGANDS_INIT,
    LIGANDS_HOLDOUT,
    exp_init,
    exp_holdout,
) = DATASET.get_init_holdout_data(SEED=777)


