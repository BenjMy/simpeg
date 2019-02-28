from __future__ import print_function
import numpy as np
import properties
from scipy.sparse import csr_matrix as csr
import dask
import dask.array as da
from . import Utils
from . import Survey
from . import ObjectiveFunction


class BaseDataMisfit(ObjectiveFunction.L2ObjectiveFunction):
    """
    BaseDataMisfit

        .. note::

            You should inherit from this class to create your own data misfit
            term.
    """

    debug   = False  #: Print debugging information
    counter = None  #: Set this to a SimPEG.Utils.Counter() if you want to count things

    _hasFields = True  #: Data Misfits take fields, handy to store them

    def __init__(self, survey, **kwargs):
        assert survey.ispaired, 'The survey must be paired to a problem.'
        if isinstance(survey, Survey.BaseSurvey):
            self.survey = survey
            self.prob   = survey.prob
        super(BaseDataMisfit, self).__init__(**kwargs)

    @property
    def nP(self):
        if self._mapping is not None:
            return self.mapping.nP
        elif self.prob.model is not None:
            return len(self.prob.model)
        else:
            return '*'

    @property
    def Wd(self):
        raise AttributeError(
            'The `Wd` property been depreciated, please use: `W` instead'
        )


class l2_DataMisfit(BaseDataMisfit):
    """

    The data misfit with an l_2 norm:

    .. math::

        \mu_\\text{data} = {1\over 2}\left|
        \mathbf{W}_d (\mathbf{d}_\\text{pred} -
        \mathbf{d}_\\text{obs}) \\right|_2^2

    """

    std = None  #: default standard deviation if not provided by survey
    eps = None  #: default floor
    eps_factor = 1e-5  #: factor to multiply by the norm of the data to create floor

    def __init__(self, survey, **kwargs):
        BaseDataMisfit.__init__(self, survey, **kwargs)

        if self.std is None:
            if getattr(self.survey, 'std', None) is None:
                print(
                    'SimPEG.DataMisfit.l2_DataMisfit assigning default std '
                    'of 5%'
                )
                self.std = 0.05
            else:
                self.std = self.survey.std

        if self.eps is None:
            if getattr(self.survey, 'eps', None) is None:
                print(
                    'SimPEG.DataMisfit.l2_DataMisfit assigning default eps '
                    'of 1e-5 * ||dobs||'
                )
                self.eps = (
                    np.linalg.norm(Utils.mkvc(survey.dobs), 2)*self.eps_factor
                )  # default
            else:
                self.eps = self.survey.eps

    @property
    def W(self):
        """W

            The data weighting matrix.

            The default is based on the norm of the data plus a noise floor.

            :rtype: scipy.sparse.csr_matrix
            :return: W

        """

        if getattr(self, '_W', None) is None:
            survey = self.survey
            self._W = Utils.sdiag(1/(abs(survey.dobs)*self.std+self.eps))

        return self._W

    @W.setter
    def W(self, value):
        if len(value.shape) < 2:
            value = Utils.sdiag(value)
        assert value.shape == (self.survey.nD, self.survey.nD), (
            'W must have shape ({nD},{nD}), not ({val0}, val{1})'.format(
                nD=self.survey.nD, val0=value.shape[0], val1=value.shape[1]
            )
        )
        self._W = value

    @Utils.timeIt
    def __call__(self, m, f=None):
        "__call__(m, f=None)"
        if f is None:
            f = self.prob.fields(m)

        W_res = dask.delayed(csr.dot)(self.W, self.survey.residual(m, f))
        vec = da.from_delayed(W_res, dtype=float, shape=[self.W.shape[1]])
#        R = self.W * self.survey.residual(m, f)
        return 0.5*da.dot(vec,vec)

    @Utils.timeIt
    def deriv(self, m, f=None):
        """
        deriv(m, f=None)

        Derivative of the data misfit

        .. math::

            \mathbf{J}^{\top} \mathbf{W}^{\top} \mathbf{W}
            (\mathbf{d} - \mathbf{d}^{obs})

        :param numpy.ndarray m: model
        :param SimPEG.Fields.Fields f: fields object
        """
        if f is None:
            f = self.prob.fields(m)

        w_d = dask.delayed(csr.dot)(
                self.W, self.survey.residual(m, f=f)
            )

        wtw_d = dask.delayed(csr.dot)(
                self.W.T, self.scale * w_d
            )

        row = da.from_delayed(wtw_d, dtype=float, shape=[self.W.shape[0]])
        return self.prob.Jtvec(m, row, f=f)

    @Utils.timeIt
    def deriv2(self, m, v, f=None):
        """
        deriv2(m, v, f=None)

        .. math::

            \mathbf{J}^{\top} \mathbf{W}^{\top} \mathbf{W} \mathbf{J}

        :param numpy.ndarray m: model
        :param numpy.ndarray v: vector
        :param SimPEG.Fields.Fields f: fields object
        """
        if f is None:
            f = self.prob.fields(m)

        jtvec = self.prob.Jvec_approx(m, v, f=f)

        w_jtvec = dask.delayed(csr.dot)(
                self.W, jtvec
            )

        wtw_jtvec = dask.delayed(csr.dot)(
                self.W.T, w_jtvec
            )

        row = da.from_delayed(wtw_jtvec, dtype=float, shape=[self.W.shape[0]])
        return self.prob.Jtvec_approx(m, row, f=f)
