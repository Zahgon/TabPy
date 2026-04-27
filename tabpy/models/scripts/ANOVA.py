import scipy.stats as stats
from tabpy.models.utils import setup_utils


def anova(_arg1, _arg2, *_argN):
    """
    ANOVA is a statistical hypothesis test that is used to compare
    two or more group means for equality.For more information on
    the function and how to use it please refer to tabpy-tools.md
    """
    pass


if __name__ == "__main__":
    setup_utils.deploy_model("anova", anova, "Returns the p-value form an ANOVA test")
