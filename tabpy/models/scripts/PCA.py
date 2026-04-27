import pandas as pd
from numpy import array
from sklearn.decomposition import PCA as sklearnPCA
from sklearn.preprocessing import StandardScaler
from sklearn.preprocessing import LabelEncoder
from sklearn.preprocessing import OneHotEncoder
from tabpy.models.utils import setup_utils


def PCA(component, _arg1, _arg2, *_argN):
    """
    Principal Component Analysis is a technique that extracts the key
    distinct components from a high dimensional space whie attempting
    to capture as much of the variance as possible. For more information
    on the function and how to use it please refer to tabpy-tools.md
    """
    pass


if __name__ == "__main__":
    setup_utils.deploy_model("PCA", PCA, "Returns the specified principal component")
