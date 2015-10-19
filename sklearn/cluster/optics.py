# -*- coding: utf-8 -*-

#                                              #
# Authors:                                     #
#     Shane Grigsby <refuge@rocktalus.com      #
#     Sean Freeman                             #
# Date:             May  2013                  #
# Updated:          Nov  2014                  #
# Benchmarked:      Sept 2015                  #

# Imports #

import scipy as sp
import numpy as np
from ..utils import check_array
from sklearn.neighbors import BallTree
from sklearn.base import BaseEstimator, ClusterMixin


class setOfObjects(BallTree):

    """Build balltree data structure with processing index from given data
    in preparation for OPTICS Algorithm

    Parameters
    ----------
    data_points: array [n_samples, n_features]"""

    def __init__(self, data_points, **kwargs):

        super(setOfObjects, self).__init__(data_points, **kwargs)

        self._n = len(self.data)
        # Start all points as 'unprocessed' ##
        self._processed = sp.zeros((self._n, 1), dtype=bool)
        self.reachability_ = sp.ones(self._n) * sp.inf
        self.core_dists_ = sp.ones(self._n) * sp.nan
        self._index = sp.array(range(self._n))
        self._nneighbors = sp.ones(self._n, dtype=int)
        # Start all points as noise ##
        self._cluster_id = -sp.ones(self._n, dtype=int)
        self._is_core = sp.zeros(self._n, dtype=bool)
        # Ordering is important below... ###
        self.ordering_ = []


def _prep_optics(self, epsilon, min_samples):
    """Prep data set for main OPTICS loop

    Parameters
    ----------
    epsilon: float or int
        Determines maximum object size that can be extracted.
        Smaller epsilons reduce run time
    min_samples: int
        The minimum number of samples in a neighborhood to be
        considered a core point

    Returns
    -------
    Modified setOfObjects tree structure"""

    self._nneighbors = self.query_radius(self.data, r=epsilon,
                                         count_only=True)

    # Only core distance lookups for points capable of being core
    mask_idx = self._nneighbors >= min_samples
    core_query = self.get_arrays()[0][mask_idx]
    # Check to see if that there is at least one cluster
    if len(core_query) >= 1:
        core_dist = self.query(core_query, k=min_samples)[0][:, -1]
        self.core_dists_[mask_idx] = core_dist


# Main OPTICS loop #


def _build_optics(setofobjects, epsilon):
    """Builds OPTICS ordered list of clustering structure

    Parameters
    ----------
    SetofObjects: Instantiated and prepped instance of 'setOfObjects' class
    epsilon: float or int
        Determines maximum object size that can be extracted. Smaller
        epsilons reduce run time. This should be equal to epsilon
        in 'prep_optics' """

    for point in setofobjects._index:
        if not setofobjects._processed[point]:
            _expandClusterOrder(setofobjects, point, epsilon)

# OPTICS helper functions; these should not be public #

# Not parallelizable. The order that entries are written to
# the 'ordering_' is important!


def _expandClusterOrder(setofobjects, point, epsilon):
    if setofobjects.core_dists_[point] <= epsilon:
        while not setofobjects._processed[point]:
            setofobjects._processed[point] = True
            setofobjects.ordering_.append(point)
            point = _set_reach_dist(setofobjects, point, epsilon)
    else:
        setofobjects._processed[point] = True    # Probably not needed... #


# As above, not parallelizable. Parallelizing would allow items in
# the 'unprocessed' list to switch to 'processed'
def _set_reach_dist(setofobjects, point_index, epsilon):

    # Assumes that the query returns ordered (smallest distance first)
    # entries. This is the case for the balltree query...

    dists, indices = setofobjects.query(setofobjects.data[point_index],
                                        setofobjects._nneighbors[point_index])

    # Checks to see if there more than one member in the neighborhood ##
    if sp.iterable(dists):

        # Masking processed values ##
        # n_pr is 'not processed'
        n_pr = indices[(setofobjects._processed[indices] < 1)[0].T]
        rdists = sp.maximum(dists[(setofobjects._processed[indices] < 1)[0].T],
                            setofobjects.core_dists_[point_index])

        new_reach = sp.minimum(setofobjects.reachability_[n_pr], rdists)
        setofobjects.reachability_[n_pr] = new_reach

        # Checks to see if everything is already processed;
        # if so, return control to main loop ##
        if n_pr.size > 0:
            # Define return order based on reachability distance ###
            return n_pr[sp.argmin(setofobjects.reachability_[n_pr])]
        else:
            return point_index

# End Algorithm #

# class OPTICS(object):


class OPTICS(BaseEstimator, ClusterMixin):

    """Estimate clustering structure from vector array

    OPTICS: Ordering Points To Identify the Clustering Structure
    Equivalent to DBSCAN, finds core sample of high density and expands
    clusters from them. Unlike DBSCAN, keeps cluster hierarchy for varying
    epsilon values. Optimized for usage on large point datasets.

    Parameters
    ----------
    eps : float, optional
    The maximum distance between two samples for them to be considered
    as in the same neighborhood. This is also the largest object size
    expected within the dataset. Lower eps values can be used after
    OPTICS is run the first time, with fast returns of labels.
    min_samples : int, optional
    The number of samples in a neighborhood for a point to be considered
    as a core point.
    metric : string or callable, optional
    The distance metric to use for neighborhood lookups. Default is
    "minkowski". Other options include “euclidean”, “manhattan”,
    “chebyshev”, “haversine”, “seuclidean”, “hamming”, “canberra”,
    and “braycurtis”. The “wminkowski” and “mahalanobis” metrics are
    also valid with an additional argument.

    Attributes
    ----------
    `core_sample_indices_` : array, shape = [n_core_samples]
        Indices of core samples.
    `labels_` : array, shape = [n_samples]
        Cluster labels for each point in the dataset given to fit().
        Noisy samples are given the label -1.
    `reachability_` : array, shape = [n_samples]
        Reachability distances per sample
    `ordering_` : array, shape = [n_samples]
        The cluster ordered list of sample indices
    `core_dists_` : array, shape = [n_samples]
        Distance at which each sample becomes a core point.
        Points which will never be core have a distance of inf.

    References
    ----------
    Ankerst, Mihael, Markus M. Breunig, Hans-Peter Kriegel, and Jörg Sander.
    "OPTICS: ordering points to identify the clustering structure." ACM SIGMOD
    Record 28, no. 2 (1999): 49-60.
    """

    def __init__(self, eps=0.5, min_samples=5, metric='minkowski', **kwargs):
        self.eps = eps
        self.min_samples = min_samples
        self.metric = metric
        self.processed = False

    def fit(self, X, y=None):
        """Perform OPTICS clustering

        Extracts an ordered list of points and reachability distances, and
        performs initial clustering using 'eps' distance specified at OPTICS
        object instantiation.

        Parameters
        ----------
        X : array [n_samples, n_features]"""

        #  Checks for sparse matrices
        X = check_array(X)

        tree = setOfObjects(X)  # ,self.metric)
        _prep_optics(tree, self.eps * 5.0, self.min_samples)
        _build_optics(tree, self.eps * 5.0)
        self._index = tree._index[:]
        self.reachability_ = tree.reachability_[:]
        self.core_dists_ = tree.core_dists_[:]
        self._cluster_id = tree._cluster_id[:]
        self._is_core = tree._is_core[:]
        self.ordering_ = tree.ordering_[:]
        _extractDBSCAN(self, self.eps)  # extraction needs to be < eps
        self.labels_ = self._cluster_id[:]
        self.core_sample_indices_ = self._index[self._is_core[:] == True]
        self.n_clusters = max(self._cluster_id)
        self.processed = True
        return self  # self.core_sample_indices_, self.labels_

    def extract(self, epsilon_prime=self.eps, clustering='dbscan',
                significant_ratio=0.75, similarity_ratio=0.4, 
                min_reach_ratio=0.1):
        """Performs DBSCAN equivalent extraction for arbitrary epsilon.
        Can be run multiple times.

        Parameters
        ----------
        epsilon_prime: float or int, optional
        Used for 'dbscan' clustering. Must be less than or equal to what 
        was used for prep and build steps
        clustering: {'dbscan', hierarchical'}, optional
        Type of cluster extraction to perform; defaults to 'dbscan'.
        significant_ratio : float, optional
        Used for hierarchical clustering. The ratio for the reachability 
        score of a local maximum compared to its neighbors to be considered 
        significant.
        similarity_ratio : float, optional
        Used for hierarchical clustering. The ratio for the reachability 
        score of a split point compared to the parent split point for it to 
        be considered similar.
        min_reach_ratio : float, optional
        Used for hierarchical clustering. The ratio of the largest 
        reachability score that a local maximum needs to reach in order to 
        be considered.
        
        Returns
        -------
        New core_sample_indices_ and labels_ arrays. Modifies OPTICS object
        and stores core_sample_indices_ and lables_ as attributes."""

        if self.processed is True:
            if epsilon_prime > self.eps * 5.0:
                print('Specify an epsilon smaller than ' + str(self.eps * 5))
            else:
                if clustering == 'dbscan':
                    self.eps_prime = epsilon_prime
                    _extractDBSCAN(self, epsilon_prime)
                elif clustering == 'hierarchical':
                    _hierarchical_extraction(self, significant_ratio, 
                                             similarity_ratio, 
                                             min_reach_ratio)   
                self.labels_ = self._cluster_id[:]
                # Setting following line to '1' instead of 'True' to keep
                # line shorter than 79 characters
                self.core_sample_indices_ = self._index[self._is_core[:] == 1]
                self.n_clusters = max(self._cluster_id)
                if epsilon_prime > (self.eps * 1.05):
                    print("Warning, eps is close to epsilon_prime:")
                    print("Output may be unstable")
                return self.core_sample_indices_, self.labels_
        else:
            print("Run fit method first")

# Extract DBSCAN Equivalent cluster structure ##

# Important: Epsilon prime should be less than epsilon used in OPTICS #


def _extractDBSCAN(setofobjects, epsilon_prime):

    # Start Cluster_id at zero, incremented to '1' for first cluster
    cluster_id = 0
    for entry in setofobjects.ordering_:
        if setofobjects.reachability_[entry] > epsilon_prime:
            if setofobjects.core_dists_[entry] <= epsilon_prime:
                cluster_id += 1
                setofobjects._cluster_id[entry] = cluster_id
            else:
                # This is only needed for compatibility for repeated scans.
                # -1 is Noise points
                setofobjects._cluster_id[entry] = -1
                setofobjects._is_core[entry] = 0
        else:
            setofobjects._cluster_id[entry] = cluster_id
            if setofobjects.core_dists_[entry] <= epsilon_prime:
                # One (i.e., 'True') for core points #
                setofobjects._is_core[entry] = 1
            else:
                # Zero (i.e., 'False') for non-core, non-noise points #
                setofobjects._is_core[entry] = 0


# Algorithm for hierarchical extraction of clusters from a reachability plot.
# Authors: Fredrik Appelros (fredrik.appelros@gmail.com), 
#          Carl Ekerot (kalle@implode.se)
# Modified: Shane Grigsby, October 2015
# License: BSD

def _hierarchical_extraction(self, significant_ratio=0.75, 
                             similarity_ratio=0.4, min_reach_ratio=0.1):
    """
    Constructs a tree structure from an OPTICS ordering and a set of
    reachability distances and extracts clusters from this structure.
    Parameters
    ----------
    significant_ratio : float
        The ratio for the reachability score of a local maximum
        compared to its neighbors to be considered significant.
    similarity_ratio : float
        The ratio for the reachability score of a split point
        compared to the parent split point for it to be considered
        similar.
    min_reach_ratio : float
        The ratio of the largest reachability score that a local
        maximum needs to reach in order to be considered.
    Returns
    -------
    labels : array [n_samples]
        Cluster labels for each point. Noisy samples are given the label -1.
    References
    ----------
    Sander, Jörg, Xuejie Qin, Zhiyong Lu, Nan Niu, and Alex Kovarsky.
    "Automatic extraction of clusters from hierarchical clustering
    representations." Advances in Knowledge Discovery and Data Mining (2003):
    567-567.
    """
    R = np.asarray([self.reachability_[i] for i in self.ordering_])
    n = len(ordering_)

    # Find local maximas
    L = []
    for i in xrange(0, self.min_samples):
        if np.argmax(R[0:i + self.min_samples + 1]) == i:
            L.append(i)
        if np.argmax(R[n - 2 * self.min_samples + i:n]) == i:
            L.append(n - self.min_samples + i)
    for i in xrange(self.min_samples, n - self.min_samples):
        if (np.argmax(R[i - self.min_samples:i + self.min_samples + 1]) == 
            self.min_samples):
            L.append(i)
    # Sort local maximas in order of their reachability
    L.sort(key=lambda x: R[x])
    R_max = R[L[-1]]
    L = filter(lambda x: R[x] >= min_reach_ratio * R_max, L)

    class Node:
        def __init__(self, left, right):
            self.left = left
            self.right = right
            self.children = []

    leaves = []
    def cluster_tree(node, parent, L):
        if not L:
            leaves.append(node)
            return

        s = node.split = L.pop()
        child_left = Node(node.left, s)
        child_right = Node(s, node.right)
        L_left  = [L[i] for i in np.where(np.asarray(L) < s)[0]]
        L_right = [L[i] for i in np.where(np.asarray(L) > s)[0]]
        R_left  = R[child_left.left:child_left.right]
        R_right = R[child_right.left:child_right.right]

        if R_left.size > 0:
            avg_reach_left = np.mean(R_left)
        else:
            avg_reach_left = 0
        if R_right.size > 0:
            avg_reach_right = np.mean(R_right)
        else:
            avg_reach_right = 0

        if avg_reach_left <= significant_ratio * R[s] >= avg_reach_right:
            children = []
            left_size = child_left.right - child_left.left
            if left_size >= self.min_samples or left_size == child_left.right:
                children.append((child_left, L_left))
            right_size = child_right.right - child_right.left
            if (right_size >= self.min_samples or right_size == 
                n - child_right.left):
                children.append((child_right, L_right))
            if not children:
                leaves.append(node)
                return

            if parent and R[s] / R[parent.split] >= similarity_ratio:
                for child, L in children:
                    parent.children.append(child)
                parent.children.remove(node)
                p = parent
            else:
                for child, L in children:
                    node.children.append(child)
                p = node
            for (child, L) in children:
                cluster_tree(child, p, L)
        else:
            cluster_tree(node, parent, L)

    root = Node(0, n)
    cluster_tree(root, None, L)

    self._cluster_id = -np.ones(n)
    for (i, leaf) in enumerate(leaves):
        for j in xrange(leaf.left, leaf.right):
            self._cluster_id[self.ordering[j]] = i
    self._is_core[self.labels == -1] = 0 
    self._is_core[self.labels_[:] >= 0] = 1

