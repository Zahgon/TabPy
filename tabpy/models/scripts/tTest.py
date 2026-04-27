from scipy import stats
from tabpy.models.utils import setup_utils


def ttest(_arg1, _arg2):
    """
    T-Test is a statistical hypothesis test that is used to compare
    two sample means or a sample’s mean against a known population mean.
    For more information on the function and how to use it please refer
    to tabpy-tools.md
    """
    pass


if __name__ == "__main__":
    setup_utils.deploy_model("ttest", ttest, "Returns the p-value form a t-test")
