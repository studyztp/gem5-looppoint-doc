import json
from typing import Dict, List
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
import numpy as np

random_seed = 627

def form_bb_id_map(bb_inst_map: Dict[str, int]) -> Dict[str, int]:
    """
    Assigns a unique ID to each basic block address.
    """
    return {addr: idx for idx, addr in enumerate(bb_inst_map.keys())}


def from_bb_id_inst_array(
    bb_id_map: Dict[str, int], bb_inst_map: Dict[str, int]
) -> List[int]:
    """
    Creates an array where each index corresponds to a basic block ID
    and holds the static instruction count for that block.
    """
    inst_array = [0] * len(bb_id_map)
    for addr, inst_count in bb_inst_map.items():
        inst_array[bb_id_map[addr]] = int(inst_count)
    return inst_array


def form_weighted_bbv_array(
    raw_bbv: Dict[str, int],
    bb_id_map: Dict[str, int],
    bb_inst_array: List[int]
) -> List[int]:
    """
    Computes a weighted basic block vector (BBV) by multiplying execution counts
    with the static instruction counts per basic block.
    """
    weighted_bbv = [0] * len(bb_id_map)
    for addr, count in raw_bbv.items():
        bb_id = bb_id_map[addr]
        weighted_bbv[bb_id] = int(count * bb_inst_array[bb_id])
    return weighted_bbv


def format_bbvs(output: Dict[str, Dict]) -> List[List[float]]:
    """
    Processes a set of regional BBVs into normalized weighted BBVs.
    """
    # Use the final region to extract the full bb_inst_map
    final_region_key = str(len(output) - 1)
    bb_inst_map = output[final_region_key]["bb_inst_map"]

    bb_id_map = form_bb_id_map(bb_inst_map)
    bb_inst_array = from_bb_id_inst_array(bb_id_map, bb_inst_map)

    bbvs: List[List[float]] = []
    for region_id in range(len(output)):
        region_data = output[str(region_id)]
        raw_bbv = region_data["global_bbv"]
        region_length = region_data["global_length"]

        weighted_bbv = form_weighted_bbv_array(raw_bbv, bb_id_map, bb_inst_array)
        normalized_bbv = [x / region_length for x in weighted_bbv]
        bbvs.append(normalized_bbv)

    return np.array(bbvs)

def reduce_data_dim_with_pca(
    bbvs: List[List[float]], n_components: int = 15
) -> np.ndarray:
    """
    Reduces the dimensionality of the BBVs using PCA.
    """

    pca = PCA(n_components=n_components, random_state=random_seed)
    reduced_bbvs = pca.fit_transform(bbvs)
    return reduced_bbvs

def k_means_clustering(
    bbvs: List[List[float]], n_clusters: int = 2
) -> np.ndarray:
    """
    Applies K-means clustering to the BBVs.
    """

    kmeans = KMeans(n_clusters=n_clusters, random_state=random_seed)
    kmeans.fit(bbvs)
    labels = kmeans.labels_
    centers = kmeans.cluster_centers_
    return labels, centers

def find_representative_regions(
    bbvs: np.ndarray, labels: np.ndarray, centers: np.ndarray
) -> Dict[int, List[int]]:
    """
    Finds representative regions for each cluster based on the closest BBV to the cluster center.
    """
    representative_regions: Dict[int, List[int]] = {}
    for i in range(len(centers)):
        cluster_indices = np.where(labels == i)[0]
        distances = np.linalg.norm(bbvs[cluster_indices] - centers[i], axis=1)
        closest_index = cluster_indices[np.argmin(distances)]
        if i not in representative_regions:
            representative_regions[i] = []
        representative_regions[i].append(closest_index)
    return representative_regions
