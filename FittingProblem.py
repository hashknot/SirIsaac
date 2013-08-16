# FittingProblem.py
#
# Bryan Daniels
# 6.29.2009 - 7.14.2009
# - 2012
# - 2013
#
# Defines FittingProblem class, which contains all the information for
# a "fitting problem": data to be fitted, a sequence of models that
# attempt to fit the model, the results of fitting, ...
#

from SloppyCell.ReactionNetworks import *
import PowerLawNetwork
reload(PowerLawNetwork)
import TranscriptionNetwork
reload(TranscriptionNetwork)
import LaguerreNetwork
reload(LaguerreNetwork)
import PolynomialNetwork
reload(PolynomialNetwork)
import PhosphorylationFit_netModel
reload(PhosphorylationFit_netModel)
import CTSNNetwork
reload(CTSNNetwork)
import PlanetaryNetwork
reload(PlanetaryNetwork)
import VaryingParamsWrapper
reload(VaryingParamsWrapper)
import GaussianPrior
reload(GaussianPrior)
import scipy.linalg
import io, os
import time
#print "This computer's name is",os.uname()[1]
if (os.uname()[1][:8] != 'vader') and (os.uname()[1][:8] != 'maul') and \
   (os.uname()[1][:8] != 'sidious') and (os.uname()[1][:4] != 'node') and \
   (os.uname()[1][:8] != 'star') and (os.uname()[1][:8] != 'spark'):
    from pygraphviz import * # for network figures
    import matplotlib.colors
if (os.uname()[1] != 'star'):
    from simulateYeastOscillator import *
import pylab
from subprocess import call # for network figures and pypar
from linalgTools import svdInverse
import copy

# used in _findUsedVariables
import SloppyCell.ExprManip as ExprManip 
import sets

from simplePickle import load,save


avegtolDefault = 1e-8
maxiterDefault = None
cutoffDefault = 1.
verboseDefault = False
maxMemoryUsageDefault = scipy.inf # 500000 ~ 500M

def UpdateOldFitProbDict(fitProbDict):
    for p in fitProbDict.values():
        p._fixOldVersion()
        # the following line only for SloppyCell networks
        for m in p.fittingModelList:
            m.net.constraints = {}
        p.perfectModel.net.constraints = {}
        for name in p.fittingModelNames:
            p._UpdateDicts(name)

# 7.6.2009
def allFitProbData(fitProbDict,dataMemberString,sort=True,normed=False):
    keysList = fitProbDict.keys()
    if sort:
        keysList.sort()
    normedStr = ''
    if normed:
        normedStr = '/key'
    resultDict = eval( 'dict([ (name, [ fitProbDict[key].'\
        +dataMemberString+'[name]'    \
        +normedStr+' for key in keysList ])'                                    \
        +' for name in fitProbDict[keysList[0]].fittingModelNames ])' )
    return keysList,resultDict

def plotAllFitProbData(fitProbDict,dataMemberString,                            \
    normed=False,logx=True,*args,**kwargs):
    keysList,dict = allFitProbData(fitProbDict,dataMemberString,normed=normed)
    if logx:
        plotFn = Plotting.semilogx
    else:
        plotFn = Plotting.plot
    Plotting.figure()
    return [ plotFn(keysList,scipy.array(dict[name]),label=name,*args,**kwargs) \
        for name in dict.keys() ]

# 7.8.2009
def meanFitProbData(fitProbDict,dataMemberString,returnDictionary=False):
    keysList = fitProbDict.keys()
    # 7.29.2009 this namesList is a quick fix that may not be what I want...
    namesList = []
    for name in fitProbDict[keysList[0]].fittingModelNames:
        if fitProbDict[keysList[0]].singValsDict.has_key(name):
            namesList.append(name)
    #dict( [ ( name, average([fitProbDict[key].function(name) 
    #for key in keysList]) ) for name in names ] )
    returnDict = eval( 'dict([ (name, scipy.average( '
        +'[ fitProbDict[key].'+dataMemberString+'[name] for key in keysList ]))'\
        +' for name in namesList ])' )
    if returnDictionary:
        return returnDict
    else:
        return [ returnDict[name] for name in namesList ]

# 7.20.2009
def plotMeanFitProbData(fitProbDict,dataStringX,dataStringY,fmt='o',neg=False):
    xdata = meanFitProbData(fitProbDict,dataStringX,returnDictionary=False)
    ydata = meanFitProbData(fitProbDict,dataStringY,returnDictionary=False)
    if neg:
        ydata = -scipy.array(ydata)
    return Plotting.plot(xdata,ydata,fmt)

# 7.26.2009 modified from meanFitProbData and plotMeanFitProbData
def allIntegratedError(fitProbDict,timeInterval,var,                           \
    indepParams=None,numPoints=500,average=True):
    """
    average     : if True, divide result by the length of the interval
    """
    keysList = fitProbDict.keys()
    # 7.29.2009 this namesList is a quick fix that may not be what I want...
    namesList = []
    for name in fitProbDict[keysList[0]].fittingModelNames:
        if fitProbDict[keysList[0]].singValsDict.has_key(name):
            namesList.append(name)
    error = [ [ fitProbDict[key].calculateIntegratedError                       \
        (fitProbDict[key].fittingModelDict[name],timeInterval,var,              \
        indepParams=indepParams,numPoints=numPoints,average=average)            \
        for key in keysList ] for name in namesList ]
    return error

# 7.27.2009
def meanExtraIntegratedError(fitProbDict,timeInterval,var,                      \
    indepParams=None,numPoints=500,average=True):
    
    totalError = scipy.array( meanIntegratedError(fitProbDict,timeInterval,     \
        var,indepParams,numPoints,average) )
        
    keysList = fitProbDict.keys()
    namesList = fitProbDict[keysList[0]].fittingModelNames
    expectedError = scipy.array([ scipy.average([                               \
        fitProbDict[key].fittingModelDict[name].expectedAvgIntegratedErr(       \
            fitProbDict[key].fittingData,fitProbDict[key].indepParamsList)      \
        for key in keysList ]) for name in namesList ])
    
    # [Note: we do want to use indepParams for the totalError (this is the
    #  case we're testing) and p.indepParamsList for the expectedError
    #  (these are the cases for the experimental data)]
        
    return totalError - expectedError



class FittingProblem:
    """
    A "fitting problem" contains data to be fitted, a sequence of models that
    attempt to fit the model, the results of fitting, ...
    
    fittingModelList        : List of models to try, in order of increasing
                              complexity.
    saveFilename            : If given, the fittingProblem is saved to
                                  the file after each fit is performed.
    """
    
    def __init__(self,fittingData,fittingModelList,fittingModelNames=None,      \
        indepParamsList=[[]],indepParamNames=[],singValCutoff=cutoffDefault,    \
        verbose=verboseDefault,perfectModel=None,saveFilename=None,             \
        bestSeenParamsDict={},smallerBestParamsDict={},saveKey=-1):
        # all daughter classes should call generalSetup
        self.generalSetup(fittingData,indepParamsList,indepParamNames,          \
            fittingModelList,singValCutoff,fittingModelNames,verbose,           \
            perfectModel,saveFilename,bestSeenParamsDict,                       \
            smallerBestParamsDict)
        # (should the singValCutoff necessarily be the same for all models?)
    
    def generalSetup(self,fittingData,indepParamsList,indepParamNames,          \
        fittingModelList,singValCutoff,fittingModelNames,verbose,perfectModel,  \
        saveFilename,bestSeenParamsDict,smallerBestParamsDict,                  \
        saveKey):
        
        if fittingModelNames is None:
            fittingModelNames =                                                 \
                [ 'Model '+str(i+1) for i in range(len(fittingModelList)) ]
        
        self.fittingData = fittingData
        self.indepParamsList = indepParamsList
        self.indepParamNames = indepParamNames
        self.fittingModelList = fittingModelList
        self.fittingModelNames = fittingModelNames
        self.cutoff = singValCutoff
        self.verbose = verbose
        self.fittingModelDict = dict( zip(fittingModelNames,fittingModelList) )
        self.costDict = {}
        self.HessianDict = {}
        self.singValsDict = {}
        self.oldLogLikelihoodDict = {}
        self.fitParametersDict = {}
        self.penaltyDict = {}
        self.numStiffSingValsDict = {}
        self.numParametersDict = {}
        self.fitAllDone = False
        
        self.perfectModel = perfectModel
        if self.perfectModel is not None:
          self.perfectParams = self.perfectModel.getParameters()
        else:
          self.perfectParams = None
        self.saveFilename = saveFilename
        self.saveKey = saveKey
        
        # I haven't been using this recently
        self.bestSeenParamsDict = bestSeenParamsDict
        
        # 4.17.2012
        self.smallerBestParamsDict = smallerBestParamsDict
        
        # 5.30.2012
        self.pid = os.getpid()
        
        # 6.1.2012
        self.stopFittingN = 3
    
    def fitAll(self,usePreviousParams=True,fitPerfectModel=False,resume=True,**kwargs):
        """
        usePreviousParams       : if True, use the previous model's 
                                  parameters as a starting point. 
                                  if False, only use the previous model's
                                  parameters when the best-fit cost is
                                  worse than the previous fit.
        resume (True)           : If True, skip fitting any models that
                                  have already been fit.
        """
        oldFitParameters = []
        oldCost = scipy.inf
        
        if fitPerfectModel:
            self.fitPerfectModel() 
            if self.saveFilename is not None:
                self.writeToFile(self.saveFilename)
            
        for name in self.fittingModelNames:
          fittingModel = self.fittingModelDict[name]
          # 4.18.2012
          if self.costDict.has_key(name) and resume:
            # We've already fit this one.  
            # Don't fit it again, but remember its parameters
            oldFitParameters = fittingModel.getParameters()
            # ****
            print "fittingProblem.fitAll debug: skipping",name
            # ****
          else:
            if self.saveFilename is not None:
                self.writeToFile(self.saveFilename)
        
            if usePreviousParams:
                fittingModel.initializeParameters(oldFitParameters)
            
            # 4.17.2012
            if self.smallerBestParamsDict.has_key(name):
                smallerBestParams = self.smallerBestParamsDict[name]
            else:
                smallerBestParams = None
                
            # 8.30.2012 get fittingDataDerivs if I have them
            fittingDataDerivs = getattr(self,'fittingDataDerivs',None)
            # 9.20.2012 XXX Should we never include priors for cost?
            if fittingDataDerivs is not None: includePriors = False
            else: includePriors = True
            
            newFitParameters =                                                  \
              fittingModel.fitToData(self.fittingData,self.indepParamsList,     \
                                     otherStartingPoint=smallerBestParams,      \
                                     fittingDataDerivs=fittingDataDerivs,**kwargs)
            
            if not hasattr(self,'fittingDataDerivs'):
                self.fittingDataDerivs = None
            if self.fittingDataDerivs is None:
                newCost =                                                           \
                  fittingModel.currentCost(self.fittingData,self.indepParamsList,   \
                                         fittingDataDerivs=fittingDataDerivs,       \
                                         includePriors=includePriors)
                # We know that the next more complex model should always have
                # a lower cost.  If it doesn't, try starting from the old
                # parameters.
                # (Note: This assumes that the default values for the new
                # parameters make the new (more complex) model behave the
                # same as the old one before they are changed.)
                if newCost > oldCost:
                    fittingModel.initializeParameters(oldFitParameters)
                    newFitParameters =                                              \
                      fittingModel.fitToData(self.fittingData,self.indepParamsList, \
                      fittingDataDerivs=fittingDataDerivs)
                    newCost =                                                       \
                      fittingModel.currentCost(self.fittingData,                    \
                        self.indepParamsList,fittingDataDerivs=fittingDataDerivs,   \
                        includePriors=includePriors)
            
                # 2.15.2012
                # check if bestSeenParamsDict has potentially better parameters
                if self.bestSeenParamsDict.has_key(name):
                  bestSeenCost = self.bestSeenParamsDict[name][0]
                  if newCost > bestSeenCost:
                    bestSeenParams = self.bestSeenParamsDict[name][1]
                    fittingModel.initializeParameters(bestSeenParams)
                    newerFitParameters =                                            \
                      fittingModel.fitToData(self.fittingData,self.indepParamsList, \
                            fittingDataDerivs=fittingDataDerivs)
                    newerCost =                                                     \
                      fittingModel.currentCost(self.fittingData,                    \
                            self.indepParamsList,fittingDataDerivs=fittingDataDerivs,\
                            includePriors=includePriors)
                    if newerCost < newCost:
                      newCost = newerCost
                      newFitParameters = newerFitParameters

            else: # don't bother when fitting derivatives
                #newCost = scipy.inf
                newCost = fittingModel.currentCost_deriv(self.fittingData,          \
                    self.indepParamsList,fittingDataDerivs,                         \
                    includePriors=includePriors)
            
            fittingModel.initializeParameters(newFitParameters)
            oldCost = newCost
            oldFitParameters = newFitParameters
            
            if self.fittingDataDerivs is None:
                #self.fitParametersDict[name] = newFitParameters
                self.costDict[name] =                                               \
                    fittingModel.currentCost(self.fittingData,self.indepParamsList, \
                        fittingDataDerivs=fittingDataDerivs,includePriors=includePriors)
                if includePriors:
                  self.HessianDict[name] =                                          \
                    fittingModel.currentHessian(self.fittingData,                   \
                        self.indepParamsList,fittingDataDerivs=fittingDataDerivs)
                else:
                  self.HessianDict[name] =                                         \
                    fittingModel.currentHessianNoPriors(self.fittingData,          \
                        self.indepParamsList,fittingDataDerivs=fittingDataDerivs)
            else: # when fitting derivatives
                #self.costDict[name] = scipy.inf
                self.costDict[name] = fittingModel.currentCost_deriv(               \
                    self.fittingData,self.indepParamsList,fittingDataDerivs,        \
                    includePriors=includePriors)
                self.HessianDict[name] = None
            self._UpdateDicts(name)
            
          # 5.6.2013 update old files if needed
          if not hasattr(self,'newLogLikelihoodDict'):
              self._UpdateDicts(name)
          if name not in self.newLogLikelihoodDict.keys():
              self._UpdateDicts(name)
                
          # 6.1.2012 stop after seeing stopFittingN models with worse logLikelihood
          orderedLs = []
          if not hasattr(self,'stopFittingN'):
              self.stopFittingN = 3
          for n in self.fittingModelNames:
              if self.newLogLikelihoodDict.has_key(n):
                  orderedLs.append(self.newLogLikelihoodDict[n])
          if (len(orderedLs) > self.stopFittingN):
            if max(orderedLs[-self.stopFittingN:]) < max(orderedLs):
              self.fitAllDone = True
              return

        self.fitAllDone = True
    
    # 7.21.2009
    def fitPerfectModel(self,otherStartingPoint=None):
        """
        (As of 9.19.2012, does not support fittingDataDerivs)
        
        otherStartingPoint  : passed to self.perfectModel.fitToData
        """
        fitParameters =                                                         \
            self.perfectModel.fitToData(self.fittingData,self.indepParamsList,  \
            otherStartingPoint=otherStartingPoint)
        self.perfectCost =                                                      \
            self.perfectModel.currentCost(self.fittingData,self.indepParamsList)
        self.perfectHessian =                                                   \
            self.perfectModel.currentHessian(self.fittingData,self.indepParamsList)
        self.perfectPriorHessian = self.perfectModel.currentHessianNoData(      \
            self.fittingData,self.indepParamsList)
        self.perfectFitParams = self.perfectModel.getParameters()
        u,s,vt = scipy.linalg.svd( self.perfectHessian )
        uP,sP,vtP = scipy.linalg.svd( self.perfectPriorHessian )
        self.perfectSingVals = s
        self.perfectPriorSingVals = sP
        self.perfectOldLogLikelihood = self.oldLogLikelihood(self.perfectCost,s)
        self.perfectNewLogLikelihood =                                          \
            self.newLogLikelihood( self.perfectCost, s, sP )
        self.perfectPenalty = self.penalty( s )
        self.perfectNumStiffSingVals = self.numStiffSingVals( s )
        self.perfectNumParameters = len( self.perfectFitParams )
        
        if self.saveFilename is not None:
            self.writeToFile(self.saveFilename)
    
    def _UpdateDicts(self,name):
        fittingModel = self.fittingModelDict[name]
        self.fitParametersDict[name] = fittingModel.getParameters()
        try:
            u,s,vt = scipy.linalg.svd( self.HessianDict[name] )
            self.singValsDict[name] = s
            # 5.6.2013
            if not hasattr(self,'oldLogLikelihoodDict'):
                self.oldLogLikelihoodDict = self.logLikelihoodDict
            self.oldLogLikelihoodDict[name] =                                       \
                self.oldLogLikelihood( self.costDict[name],self.singValsDict[name] )
            self.penaltyDict[name] = self.penalty( self.singValsDict[name] )
            self.numStiffSingValsDict[name] =                                       \
                self.numStiffSingVals( self.singValsDict[name] )
            # 5.2.2013
            if not hasattr(self,'priorHessianDict'):
                self.priorHessianDict = {}
                self.priorSingValsDict = {}
                self.newLogLikelihoodDict = {}
            self.priorHessianDict[name] = fittingModel.currentHessianNoData(        \
                self.fittingData,self.indepParamsList)
            uP,sP,vtP = scipy.linalg.svd( self.priorHessianDict[name] )
            self.priorSingValsDict[name] = sP
            self.newLogLikelihoodDict[name] =                                       \
                self.newLogLikelihood( self.costDict[name],self.singValsDict[name], \
                                       self.priorSingValsDict[name] )
        except ValueError: # in case Hessian is infinite, etc.
            self.singValsDict[name] = None
            self.oldLogLikelihoodDict[name] = scipy.inf
            self.penaltyDict[name] = scipy.inf
            self.numStiffSingValsDict[name] = None
            # 5.2.2013
            self.newLogLikelihoodDict[name] = scipy.inf
            self.priorSingValsDict[name] = None
            self.priorHessianDict[name] = None
        self.numParametersDict[name] = len( self.fitParametersDict[name] )
    
    def oldLogLikelihood(self,cost,singVals,cutoff=None):
        """
        Calculate log-likelihood estimate based on cost (usu. sums of
        squared residuals) and the singular values of the Hessian, cutting
        off singular values less than a given cutoff.
        
        cutoff      : if None, use self.cutoff
        """
        #if cutoff is None:
        #   cutoff = self.cutoff
        #prod = 1
        #for singVal in singVals:
        #   if singVal > cutoff:
        #       prod *= singVal
        #return -(cost + 0.5*scipy.log(prod))
        
        return -(cost + self.penalty(singVals,cutoff))
    
    # 5.2.2013
    def newLogLikelihood( self,cost,singVals,priorSingVals ):
        """
        Calculate log-likelihood estimate based on cost (usu. sums of
        squared residuals), the singular values of the Hessian, and 
        the singular values of the Hessian with only priors.
        """
        return -(cost + 0.5*scipy.sum( scipy.log(singVals) )                    \
                      - 0.5*scipy.sum( scipy.log(priorSingVals) ) )

    
    # 8.2.2009 updated to include 2pi
    def penalty(self,singVals,cutoff=None):
        return 0.5*scipy.sum( scipy.log(                                        \
            scipy.array(self._StiffSingVals(singVals,cutoff))/(2.*scipy.pi) ) )
    
    def numStiffSingVals(self,singVals,cutoff=None):
        return len( self._StiffSingVals(singVals,cutoff) )
    
    def _StiffSingVals(self,singVals,cutoff=None):
        if cutoff is None:
            cutoff = self.cutoff
        return filter(lambda s: s>cutoff, singVals)
    
    def plotResults(self,subplotConfig=None,showTitles=True,showInfo=True,      \
        errorBars=True,exptsToPlot=None,plotDerivs=False,**kwargs):
        
        if not self.fitAllDone:
            print "FittingProblem.plotResults warning: "                        \
                 +"some or all fits have not yet been performed."
        
        if subplotConfig is not None:
            subplotRows,subplotCols = subplotConfig
        else:
            subplotRows,subplotCols = 1,1
            
        for i,name in enumerate(self.fittingModelNames):
            fittingModel = self.fittingModelDict[name]
            curPosition = i%(subplotRows*subplotCols) + 1
            if curPosition == 1:
                Plotting.figure()
            Plotting.subplot(subplotRows,subplotCols,curPosition)
            fittingModel.plotResults(self.fittingData,self.indepParamsList,     \
                errorBars=errorBars,exptsToPlot=exptsToPlot,plotDerivs=plotDerivs,\
                **kwargs)
            if showTitles:
                extraInfo = ''
                if showInfo:
                    extraInfo = ' ' + str(self.numParametersDict[name])         \
                        + '(' + str(self.numStiffSingValsDict[name]) + ')'
                if subplotConfig is not None:
                    Plotting.title(self.fittingModelNames[i]+extraInfo)
                else: # 12.5.2012
                    fig = Plotting.gcf()
                    fig.canvas.set_window_title(self.fittingModelNames[i]+extraInfo)
            
            
    
    def plotithEigenvector(self,fittingModelName,i,showTitle=True):
        """
        fittingModelName: name of fittingModel in the fittingProblem, 
                          or an integer index of the name in the list 
                          self.fittingModelNames
        i               : 0 for stiffest, -1 for sloppiest
        
        (actually singular vector, not eigenvector)
        """
        if type(fittingModelName) != str:
            fittingModelName = self.fittingModelNames[fittingModelName]
        
        try:
            paramNames = self.fitParametersDict[fittingModelName].keys()
        except:
            paramNames = None
            
        u,s,vt = scipy.linalg.svd( self.HessianDict[fittingModelName] )
            
        Plotting.figure()
        plot = Plotting.plot_eigvect(vt[i],labels=paramNames)
        if showTitle:
            Plotting.title(fittingModelName+", singular value = "+str(s[i]))
        return plot
    
    def plotSingularValues(self,withPriors=True,newPlot=True,widths=0.9,       \
        labelRotation=0):
        
        if newPlot:
            Plotting.figure()
        
        names = self.fittingModelNames
        for i,name in enumerate(names):
            m = self.fittingModelDict[name]
            if withPriors:
                if self.singValsDict.has_key(name):
                    singVals = self.singValsDict[name]
                else:
                    #hess = m.currentHessian(self.fittingData,                  \
                    #self.indepParamsList)
                    singVals = scipy.array([])
            else:
                fittingDataDerivs = getattr(self,'fittingDataDerivs',None)
                hess = m.currentHessianNoPriors(self.fittingData,               \
                    self.indepParamsList,fittingDataDerivs=fittingDataDerivs)
                u,singVals,vt = scipy.linalg.svd(hess)
            Plotting.plot_eigval_spectrum(singVals,                             \
                offset=i,widths=widths)
                
        Plotting.xticks( 0.5 + scipy.arange(len(names)), names,                 \
            rotation=labelRotation )
        
        #plots = [ Plotting.semilogy(self.singValsDict[name],'o',label=name)    \
        #   for name in self.fittingModelNames ]
        #if show_legend:
        #   Plotting.legend()
        #return plots
    
    # 11.7.2011
    #def plotLogLikelihoods(self,**kwargs):
    #    fitModelNames = filter(lambda name:                                     \
    #        self.logLikelihoodDict.has_key(name), self.fittingModelNames)
    #    return Plotting.plot(range(1,1+len(fitModelNames)),                     \
    #        [self.logLikelihoodDict[n] for n in fitModelNames],**kwargs)
    
    def showImages(self,subplotConfig=None,showTitles=True):
        import Image
        
        if subplotConfig is not None:
            subplotRows,subplotCols = subplotConfig
        else:
            subplotRows,subplotCols = 1,1
            
        for i,fittingModel in enumerate(self.fittingModelList):
            curPosition = i%(subplotRows*subplotCols) + 1
            if curPosition == 1:
                Plotting.figure()
            Plotting.subplot(subplotRows,subplotCols,curPosition)
            if fittingModel.image != None:
                im = Image.open(fittingModel.image)
                Plotting.imshow(im)
            if showTitles:
                Plotting.title(self.fittingModelNames[i])

    
    def _allNonzeroSingVals(self):
        if len(self.singValsDict.values()) == 0:
            return []
        else:
            allSingVals = Plotting.concatenate(self.singValsDict.values())
            return allSingVals[allSingVals.nonzero()]
    
    # 4.18.2012 changed to save to dictionary of FittingProblems
    def writeToFile(self,filename):
        currentFitProbDict = Utility.load(filename)
        currentFitProbDict[self.saveKey] = self
        Utility.save(currentFitProbDict,filename)
        #Utility.save(self,filename)
    
    # 7.8.2009
    def errorAtTime(self,fittingModelName,time,var,indepParams=None,            \
        useMemoization=True):
        """
        fittingModelName: name of fittingModel in the fittingProblem, 
                          or an integer index of the name in the list 
                          self.fittingModelNames
        time            : time at which to check prediction error
        indepParams     : indepParams at which to check prediction error
                          (if None, defaults to self.indepParamsList[0])
        """
        if indepParams is None:
            indepParams = self.indepParamsList[0]
        
        if self.perfectModel is None:
            raise Exception,                                                    \
                "No perfectModel has been defined for this fittingProblem."
        
        if type(fittingModelName) != str:
            fittingModelName = self.fittingModelNames[fittingModelName]
        fittingModel = self.fittingModelDict[fittingModelName]
        
        if useMemoization: # remember the values you've already calculated
          if not hasattr(self,'modelEvalDict'):
            self.modelEvalDict = {}
          indepParamsT = tuple(indepParams)
          name = fittingModelName
          
          if self.modelEvalDict.has_key((time,var,indepParamsT)):
            actualValue = self.modelEvalDict[(time,var,indepParamsT)]
          else:
            actualValue = self.perfectModel.evaluate(time,var,indepParams)
            self.modelEvalDict[(time,var,indepParamsT)] = actualValue
          
          if self.modelEvalDict.has_key((name,time,var,indepParamsT)):
            predictedValue = self.modelEvalDict[(name,time,var,indepParamsT)]
          else:
            predictedValue = fittingModel.evaluate(time,var,indepParams)
            self.modelEvalDict[(name,time,var,indepParamsT)] = predictedValue
        
        else:
          predictedValue = fittingModel.evaluate(time,var,indepParams)
          actualValue = self.perfectModel.evaluate(time,var,indepParams)
        
        return predictedValue - actualValue

    def clearMemoization(self):
        """
        Clear memoized values.
        """
        if hasattr(self,'modelEvalDict'):
            delattr(self,'modelEvalDict')
    
    
    def calculateIntegratedError(self,fittingModel,timeInterval,var,        \
        indepParams=None,numPoints=513,fitParams=None,ens=None,average=True,\
        retall=True):
        """
        Uses scipy.integrate.romb (Romberg integration) and evaluateVec.
        
        ens             : If given, the error will be calculated for the
                        : average output over the ensemble of parameters given.
        retall          : If True, return errorValue,times,outputs,perfectOutputs
        """
        
        # ****** copied from errorAtTime
        if indepParams is None:
            indepParams = self.indepParamsList[0]
        
        if self.perfectModel is None:
            raise Exception,                                                    \
                "No perfectModel has been defined for this fittingProblem."
        
        if fitParams is not None:
            fittingModel.initializeParameters(fitParams)
        
        # Romberg integrator insists that numPoints = 2**integer + 1
        numPoints = 2**(scipy.ceil(scipy.log2(numPoints-1))) + 1
        
        times = scipy.linspace(timeInterval[0],timeInterval[1],numPoints)
        dt = times[1] - times[0]

        # First integrate perfect model
        # 7.30.2009 a necessary addition...
        self.perfectModel.initializeParameters(self.perfectParams)
        perfectOutput = self.perfectModel.evaluateVec(times,var,indepParams)

        # Integrate model (or average ensemble of models)
        if ens is not None:
          # find average trajectory over the ensemble for the given indepParams
          ensembleTrajs = Ensembles.ensemble_trajs(                             \
            fittingModel._SloppyCellNet(indepParams),times,ens)
          modelOutput = Ensembles.traj_ensemble_quantiles(                      \
            ensembleTrajs,(0.5,))[0].get_var_traj(var)
        else:
          try:
            modelOutput = fittingModel.evaluateVec(times,var,indepParams)
          except Utility.SloppyCellException:
            print "FittingProblem.calculateIntegratedError: Warning:"
            print "  Error in integrating model output.  Returning nan."
            if retall:
              return scipy.nan,times,scipy.repeat(scipy.nan,len(times)),perfectOutput
            else:
              return scipy.nan

        errors = ( modelOutput - perfectOutput )**2
        integratedError = scipy.integrate.romb(errors,dt)
            
        if average:
          integratedError = integratedError / (timeInterval[1]-timeInterval[0])
        
        if retall:
          return integratedError,times,modelOutput,perfectOutput
        else:
          return integratedError

    # 2.29.2012
    def correlationWithPerfectModel(self,fittingModel,timeInterval,             \
        var,numPoints=100,indepParamsList=None,makePlots=False,numCols=2,       \
        returnErrors=False):
        """
        Computes data for numPoints equally-spaced data points in the
        given timeInterval for both the given fittingModel and
        self.perfectFittingModel, and returns the Pearson correlation
        coefficient.  (Returns a list of coefficients if given a 
        list of sets of independent parameters.)
        
        Returns list of shape (# indepParams, # variables).
        
        var                         : Individual name or list of names
                                      of variables to test.
        indepParamsList (None)      : Defaults to self.indepParamsList
        makePlots (False)           : Make plots
        numCols (2)                 : Use with makePlots=True
        returnErrors (False)        : If True, also return mean squared
                                      errors:
                                      mean( (data - perfectData)^2 )
        """
        flat = lambda a: scipy.reshape(a,scipy.prod(scipy.shape(a)))
        
        if indepParamsList is None:
            indepParamsList = self.indepParamsList
        if (self.perfectModel is None) and (self.saveFilename.find('wormData') < 0):
            raise Exception, "fittingProblem instance has no perfectModel."
        corrList,errList = [],[]
        times = scipy.linspace(timeInterval[0],timeInterval[1],numPoints)
        if len(scipy.shape(var)) == 0: var = [var] # single variable
        
        # 4.17.2013 don't want to return anything if we're testing a fit version
        # of self.perfectModel and it hasn't been fit yet
        if (fittingModel == self.perfectModel) and (not hasattr(self,'perfectFitParams')):
            print "correlationWithPerfectModel: Warning: Attempting to test "\
                  "fit self.perfectModel, but self.perfectModel has not yet "\
                  "been fit.  Returning nan."
            if returnErrors:
                return [scipy.nan],[scipy.nan]
            else:
                return [scipy.nan]
        
        for indepParams in indepParamsList:
          
          # 7.12.2012 for use with speedDict from George worm data
          if self.saveFilename.find('wormData') >= 0:
            wormData = speedDict[indepParams]
            times = scipy.sort(wormData.keys())
            perfectData = scipy.array([[ wormData[time][0] for time in times ]])
          #print scipy.shape(perfectData)
          #print scipy.shape(data)
          else: # typical case
            # 4.17.2013 in case we're checking a fit version of self.perfectModel
            if hasattr(self,'perfectParams'):
              if self.perfectParams is not None:
                self.perfectModel.initializeParameters(self.perfectParams)
            perfectData = self.perfectModel.evaluateVec(times,var,indepParams)
            if hasattr(self,'perfectFitParams'):
              self.perfectModel.initializeParameters(self.perfectFitParams)
                
          corrListI,errListI = [],[]
          data = fittingModel.evaluateVec(times,var,indepParams)
          
          if makePlots: 
            pylab.figure()
            cW = Plotting.ColorWheel()
            numRows = scipy.ceil(float(len(var))/numCols)
        
          for i,v,d,pd in zip(range(len(var)),var,data,perfectData):
            d = flat(d)
            pd = flat(pd)
            corr,p = scipy.stats.pearsonr(d,pd)
            corrListI.append(corr)
            meansqerr = scipy.mean( (d - pd)**2 )
            errListI.append(meansqerr)
            if makePlots:
                Plotting.subplot(numRows,numCols,i+1)
                color,tmp,tmp = cW.next()
                pylab.plot(d,'-',color=color,label="Model "+v)
                pylab.plot(pd,'o',color=color,label="Actual "+v)
                pylab.ylabel(v)
                #pylab.legend()
          corrList.append(corrListI)
          errList.append(errListI)
        
        if returnErrors:
              return scipy.array(corrList),scipy.array(errList)
        else:
              return scipy.array(corrList)
            
    # 2.29.2012
    def outOfSampleCorrelation(self,fittingModel,timeInterval,                  \
        var,indepParamsRanges,numTests=10,seed=100,verbose=True,                \
        sampleInLog=False,**kwargs):
        """
        See correlationWithPerfectModel.
        
        Returns list of shape (numTests, # variables).
        """
        
        # 7.12.2012 for use with speedDict from George worm data
        # ignores timeInterval,var,indepParamsRanges
        # tries to use seed=inputsSeed from runFittingProblem
        if self.saveFilename.find('wormData') >= 0:
            try:
                seedsStr = self.saveFilename[self.saveFilename.find('seeds'):]
                inputsSeed = seedsStr[seedsStr.find('_')+1]
                scipy.random.seed(int(inputsSeed))
                #print "outOfSampleCorrelation: using seed",inputsSeed
            except:
                scipy.random.seed(seed)
                print "outOfSampleCorrelation: Warning: error finding inputsSeed"
            indepParamsList = speedDict.keys()
            scipy.random.shuffle(indepParamsList)
            randomIndepParams = indepParamsList[-numTests:]
            #randomIndepParams = indepParamsList[:40] # for in-sample
        
        else: # typical case
            # generate random indepParams
            scipy.random.seed(seed)
            ipr = scipy.array(indepParamsRanges)
            if sampleInLog: ipr = scipy.log(ipr)
            randomIndepParams = scipy.rand(numTests,len(indepParamsRanges))*    \
                (ipr[:,1]-ipr[:,0]) + ipr[:,0]
            if sampleInLog: randomIndepParams = scipy.exp(randomIndepParams)
            if verbose: print randomIndepParams
        
        return self.correlationWithPerfectModel(fittingModel,timeInterval,      \
            var,indepParamsList=randomIndepParams,**kwargs)
    
        
    # 4.7.2012
    def calculateAllOutOfSampleCorrelelation(self,timeInterval,var,             \
        indepParamsRanges,numTests=10,filename=None,verbose=True,               \
        veryVerbose=False,**kwargs):
        if not hasattr(self,'outOfSampleCorrelationDict'):
            self.outOfSampleCorrelationDict = {}
        # we want only models that have actually been fit
        fitModelNames = filter(lambda name:                                     \
            self.newLogLikelihoodDict.has_key(name), self.fittingModelNames)
        for fName in fitModelNames:
            if verbose: print "calculateAllOutOfSampleCorrelelation:",fName
            f = self.fittingModelDict[fName]
            corrs = self.outOfSampleCorrelation(f,timeInterval,var,             \
                indepParamsRanges,numTests=numTests,verbose=veryVerbose,**kwargs)
            self.outOfSampleCorrelationDict[fName] = corrs
            if filename is not None: save(self,filename)
    
    # 4.17.2012
    # 5.2.2013 updated to use new log-likelihood
    def maxLogLikelihoodName(self,maxIndex=-3,verbose=True):
        """
        maxIndex (-3)     : If the best model has an index above maxIndex,
                            return None.  (Use negative number -N to force 
                            N-1 models to be worse before declaring
                            one the winner.)
        """
        if not hasattr(self,'newLogLikelihoodDict'):
            print "maxLogLikelihoodName: no log-likelihoods.  Returning None."
            return None
        
        modelsThatHaveBeenFit = filter(                                         \
            lambda name: self.newLogLikelihoodDict.has_key(name),               \
                                                        self.fittingModelNames)
        numModelsFit = len(modelsThatHaveBeenFit)
        if numModelsFit == 0:
            print "maxLogLikelihoodName: numModelsFit == 0.  Returning None."
            return None
        bestIndex = scipy.argsort(                                              \
            [self.newLogLikelihoodDict[n] for n in modelsThatHaveBeenFit ])[-1]
        bestModelName = self.fittingModelNames[bestIndex]
        
        if not self.fitAllDone:
            print "maxLogLikelihoodName: Warning: "                             \
                "Only "+str(numModelsFit)+" of "                                \
                +str(len(self.fittingModelNames))+" fits have been performed."
        
        # check that we're not past maxIndex
        if bestIndex > (maxIndex+numModelsFit)%numModelsFit:
            if verbose:
                print "maxLogLikelihoodName: bestIndex > maxIndex.  Returning None."
            return None
        
        return bestModelName
    
    # 4.19.2012
    def getBestModel(self,modelName=None,**kwargs):
        if modelName is None: bestModelName = self.maxLogLikelihoodName(**kwargs)
        else: bestModelName = modelName
        if bestModelName is not None:
            return self.fittingModelDict[bestModelName]
        else:
            return None
        
    # 4.19.2012
    def plotBestModelResults(self,filename=None,**kwargs):
        m = self.getBestModel(**kwargs)
        
        plots = m.plotResults(                                                  \
                    self.fittingData,self.indepParamsList)
        if self.perfectModel is not None:
            ni,no = m.numInputs,m.numOutputs
            speciesToPlot = m.speciesNames[ni:(ni+no)]
            self.perfectModel.plotResults(self.fittingData,                     \
                self.indepParamsList,fmt=[[0.65,0.65,0.65],'','-'],             \
                numRows=len(m.speciesNames),linewidth=0.5,                      \
                dataToPlot=speciesToPlot,newFigure=False,rowOffset=ni)
        
        # 7.12.2012 worm data
        # speedDict must have been imported using importWormData_George
        if self.saveFilename.find('wormData') >= 0:
            for i,indepParams in enumerate(self.indepParamsList):
                Plotting.subplot(len(m.speciesNames),len(self.indepParamsList), \
                                 m.numInputs*len(self.indepParamsList) + i+1)
                data = speedDict[indepParams]
                times = scipy.sort(data.keys())
                speeds = [ data[time][0] for time in times ]
                Plotting.plot(times,speeds,',',mec='0.6',zorder=-1)
        
        if filename is not None: Plotting.savefig(filename)
        
        return plots
    
    # 4.19.2012
    def saveBestModelAnalysis(self,filenamePrefix=None,openFiles=True,          \
        modelName=None,showWeights=False,**kwargs):
        """
        modelName (None)         : Defaults to max log likelihood model name.
        """
        if modelName is None: name = self.maxLogLikelihoodName()
        else: name = modelName
        
        # set up the filenamePrefix
        if filenamePrefix is None:
            if self.saveFilename is None:
                raise Exception, "No filenamePrefix or self.saveFilename."
            i = self.saveFilename.find('_')
            filenamePrefix = self.saveFilename[:i] + '_' + name.replace(' ','_')
            if hasattr(self,'saveKey'):
                filenamePrefix = filenamePrefix + '_' + str(self.saveKey)
                    
        self.plotBestModelResults(filename=filenamePrefix+"_plotResults.png",   \
            modelName=modelName,**kwargs)
        if hasattr(self,'networkFigureBestModel'):
            self.networkFigureBestModel(filenamePrefix+"_networkFigure",        \
                modelName=modelName,showWeights=showWeights)
        
        print "Model name:",name
        print "Num. params:",self.numParametersDict[name]
        print "Num. stiff sing. vals.:",self.numStiffSingValsDict[name]
        
        #if doOutOfSample:
        #    self.calculateAllOutOfSampleCorrelelation(XXX
        if openFiles:
            call(["open",filenamePrefix+"_plotResults.png"])
            call(["open",filenamePrefix+"_networkFigure.png"])
    
    def _calculateIntegratedErrorSlow(self,fittingModel,timeInterval,var,       \
        indepParams=None,useMemoization=True,average=True):
        """
        Uses scipy.integrate.quadrature and evaluateVec.
        """
        
        if indepParams is None:
            indepParams = self.indepParamsList[0]
        
        if self.perfectModel is None:
            raise Exception,                                                    \
                "No perfectModel has been defined for this fittingProblem."

        errorFunc = lambda times: ( fittingModel.evaluateVec(times,var,indepParams)\
            - self.perfectModel.evaluateVec(times,var,indepParams) )**2
        integratedError,err =                                                   \
            scipy.integrate.quadrature(errorFunc,timeInterval[0],timeInterval[1])
            
        if average:
          integratedError = integratedError / (timeInterval[1]-timeInterval[0])
          err = err / (timeInterval[1]-timeInterval[0])
            
        return integratedError,err
        
    def _calculateIntegratedErrorSlower(self,fittingModelName,timeInterval,var, \
        indepParams=None,useMemoization=True,average=True):
        """
        Uses scipy.integrate.quad and evaluate.
        """
        errorFunc = lambda time: ( self.errorAtTime(fittingModelName,           \
            time,var,indepParams,useMemoization) )**2
        integratedError,err =                                                   \
            scipy.integrate.quad(errorFunc,timeInterval[0],timeInterval[1])
            
        if average:
          integratedError = integratedError / (timeInterval[1]-timeInterval[0])
          err = err / (timeInterval[1]-timeInterval[0])
            
        return integratedError,err
                            
    def _fixOldVersion(self):
        """
        To update old versions: indepParams -> indepParamsList
        """
        if hasattr(self,'indepParams'):
            setattr(self,'indepParamsList',self.indepParams)
            
        newAttrs = ['fitParametersDict','penaltyDict',                          \
            'numStiffSingValsDict','numParametersDict']
        newValues = [{},{},{},{}]
        
        for newAttr,newValue in zip(newAttrs,newValues):
            if not hasattr(self,newAttr):
                setattr(self,newAttr,newValue)
                
        if self.indepParamsList == []:
            self.indepParamsList = [[]]
            self.fittingData = [self.fittingData]
            
        # 7.21.2009 fix perfectModel
        self.perfectModel.indepParamNames = self.indepParamNames
        if len(self.indepParamNames)>0:
            self.perfectModel.noIndepParams = False
        else:
            self.perfectModel.noIndepParams = True


class PowerLawFittingProblem(FittingProblem):
    """
    7.2.09 Now includes possibility of priors favoring parameters that are 
    smaller in magnitude. (set priorSigma=None for no priors)
    """
    
    def __init__(self,complexityList,fittingData,indepParamsListList=[[]],      \
        indepParamNames=[],outputNames=['output'],                              \
        graphListNames=None,graphListImages=None,avegtol=avegtolDefault,        \
        maxiter=maxiterDefault,singValCutoff=cutoffDefault,priorSigma=None,     \
        ensGen=None,verbose=verboseDefault,perfectModel=None,saveFilename=None, \
        bestSeenParamsDict={},                                                  \
        includeDerivs=False,useClampedPreminimization=False,                    \
        smallerBestParamsDict=None,saveKey=-1,fittingDataDerivs=None,           \
        useFullyConnected=False,**kwargs):
        """
        useFullyConnected (False)       : Treat complexityList as numSpeciesList
                                          and make fully connected models.
                                          (Note: sets the number of species in
                                          the model equal to the number of
                                          species represented in fittingData[0]).
        """
        
        if graphListImages is None:
            graphListImages = [ None for complexity in complexityList ]
        
        if not useFullyConnected:
            fittingModelList = [                                                    \
              PowerLawFittingModel_Complexity(complexity,outputNames=outputNames,   \
                indepParamNames=indepParamNames,image=image,                        \
                priorSigma=priorSigma,avegtol=avegtol,maxiter=maxiter,ensGen=ensGen,\
                verbose=verbose,                                                    \
                includeDerivs=includeDerivs,                                        \
                useClampedPreminimization=useClampedPreminimization,**kwargs)
              for complexity,image in zip(complexityList,graphListImages) ]
        else:
            numSpecies = len(fittingData[0].keys())
            fittingModelList = [                                                    \
              PowerLawFittingModel_FullyConnected(numSpecies,fracParams=complexity, \
                outputNames=outputNames,indepParamNames=indepParamNames,image=image,\
                priorSigma=priorSigma,avegtol=avegtol,maxiter=maxiter,ensGen=ensGen,\
                verbose=verbose,includeDerivs=includeDerivs,                        \
                useClampedPreminimization=useClampedPreminimization,**kwargs)
              for complexity,image in zip(complexityList,graphListImages) ]
        
        # all daughter classes should call generalSetup
        self.generalSetup(fittingData,indepParamsListList,indepParamNames,      \
            fittingModelList,singValCutoff,graphListNames,verbose,perfectModel, \
            saveFilename,bestSeenParamsDict,                                    \
            smallerBestParamsDict,saveKey)
            
        self.priorSigma = priorSigma
        self.convFlagDict = {}
        
        # 8.30.2012
        self.fittingDataDerivs = fittingDataDerivs
    
    def fitAll(self,**kwargs):
        FittingProblem.fitAll(self,**kwargs)
        # we also want to save the convergence information in a
        # convenient location:
        for name in self.fittingModelNames:
            self.convFlagDict[name] = self.fittingModelDict[name].convFlag
            
    def networkFigureBestModel(self,filename,modelName=None,**kwargs):
        """
        Passes on kwargs to networkList2DOT.
        """
        bestModel = self.getBestModel(modelName=modelName)
        
        # 9.5.2012 also pass edge parameters
        # (see CTSNFittingProblem version if you want to mess with maxIndepParams)
        params = bestModel.getParameters()
        netList = bestModel.networkList
        for nodeIndex in range(len(netList)):
            for neighborIndex in netList[nodeIndex][1].keys():
                pG = params.getByKey('g_'+str(nodeIndex)+'_'+str(neighborIndex))
                pH = params.getByKey('h_'+str(nodeIndex)+'_'+str(neighborIndex))
                netList[nodeIndex][1][neighborIndex] = (pG,pH)
        #print netList
        
        return networkList2DOT(netList,bestModel.speciesNames,                  \
                bestModel.indepParamNames,filename,**kwargs)

      
    # 1.9.2013
    # 2.26.2013
    def outOfSampleCorrelation_deriv(self,fittingModel,varList,                     \
      perfectIndepParamsRanges=None,timeRange=None,                                 \
      numTests=100,indepParamsSeed=1000,timeSeed=1001,makePlots=False):
      """
      Computes data and derivatives for both the given fittingModel and
      self.perfectFittingModel, and returns the Pearson correlation
      coefficient over the list of indepParams.  (NOTE: This is different
      than the behavior of correlationWithPerfectModel.)
      
      Tests the ability of the fittingModel to predict derivatives given
      concentrations.
      
      Returns array of length len(varList).
      
      (To test the derivative function at t = 0, use timeRange=[0.,0.].)
      
      
      varList                   : Names of variables to test.  For 
                                  "composite" variables, eg S2 = S2A*S2B,
                                  use the format [('S2A','S2B')].
      perfectIndepParamsRanges  : Range for each independent parameter in 
                                  self.perfectModel.indepParamNames.
                                  Defaults to 
                                  self.perfectModel.typicalIndepParamRanges().
                                  Shape (#indepParams)x(2)
      timeRange (None)          : Range of times at which to take data from the
                                  perfect model.  Defaults to 
                                  self.perfectModel.typicalTimeRange
      
      Returns list of length len(varList).
      """
      
      if perfectIndepParamsRanges is None:
        perfectIndepParamsRanges = self.perfectModel.typicalIndepParamRanges()
      if timeRange is None:
        timeRange = self.perfectModel.typicalTimeRange
      
      # () generate perfect model data
      # we do calculations using all visible variables and take the
      # ones we want at the end (otherwise we could be missing visible
      # variables during the calculation)
      perfectVars = fittingModel.speciesNames #self.perfectModel.speciesNames
      perfectNoise = 0.
      indepParamsList,fittingData,fittingDataDerivs =                               \
        self.perfectModel.generateData_deriv(perfectVars,numTests,perfectNoise,     \
        indepParamsSeed=indepParamsSeed,timeAndNoiseSeed=timeSeed,                  \
        timeRange=timeRange,indepParamsRanges=perfectIndepParamsRanges)
      
      # () compare with output of given fittingModel
      corrs,pVals = fittingModel._derivProblem_outOfSampleCorrelation(              \
            fittingData,fittingDataDerivs,indepParamsList,makePlot=makePlots,       \
            varList=varList)
       
      corr = scipy.array(corrs) #[desiredVarIndices]
      
      return corr


# 7.29.2009 blatantly copied from PowerLawFittingProblem
class CTSNFittingProblem(FittingProblem):
    """
    7.2.09 Now includes possibility of priors favoring parameters that are 
    smaller in magnitude. (set priorSigma=None for no priors)
    """
    
    def __init__(self,complexityList,fittingData,indepParamsListList=[[]],      \
        indepParamNames=[],outputNames=['output'],                              \
        graphListNames=None,graphListImages=None,avegtol=avegtolDefault,        \
        maxiter=maxiterDefault,singValCutoff=cutoffDefault,priorSigma=None,     \
        ensGen=None,verbose=verboseDefault,perfectModel=None,saveFilename=None, \
        bestSeenParamsDict={},                                                  \
        includeDerivs=False,useClampedPreminimization=False,                    \
        smallerBestParamsDict=None,saveKey=-1,switchSigmoid=False,**kwargs):
        
        if graphListImages is None:
            graphListImages = [ None for complexity in complexityList ]
            
        fittingModelList = [                                                    \
          CTSNFittingModel(complexity,outputNames=outputNames,                  \
            switchSigmoid=switchSigmoid,                                        \
            indepParamNames=indepParamNames,image=image,                        \
            priorSigma=priorSigma,avegtol=avegtol,maxiter=maxiter,ensGen=ensGen,\
            verbose=verbose,includeDerivs=includeDerivs,                        \
            useClampedPreminimization=useClampedPreminimization,                \
            **kwargs)
          for complexity,image in zip(complexityList,graphListImages) ]
        
        # all daughter classes should call generalSetup
        self.generalSetup(fittingData,indepParamsListList,indepParamNames,      \
            fittingModelList,singValCutoff,graphListNames,verbose,perfectModel, \
            saveFilename,bestSeenParamsDict,                                    \
            smallerBestParamsDict,saveKey)
            
        self.priorSigma = priorSigma
        self.convFlagDict = {}
        self.switchSigmoid = switchSigmoid
        
        if not includeDerivs: self.fittingDataDerivs = None
    
    def fitAll(self,**kwargs):
        FittingProblem.fitAll(self,**kwargs)
        # we also want to save the convergence information in a
        # convenient location:
        for name in self.fittingModelNames:
            self.convFlagDict[name] = self.fittingModelDict[name].convFlag
            
    def networkFigureBestModel(self,filename,modelName=None,indepParamMax=None,**kwargs):
        """
        Passes on kwargs to networkList2DOT.
        
        indepParamMax (None)    : List of maximum values for indep params
        """
        bestModel = self.getBestModel(modelName=modelName)
        
        if indepParamMax is None:
            indepParamMax = [ max(l) for l in scipy.transpose(self.indepParamsList) ]
        print indepParamMax
        
        # 7.26.2012 also pass edge parameters
        params = bestModel.getParameters()
        netList = bestModel.networkList
        for nodeIndex in range(len(netList)):
          for neighborIndex in netList[nodeIndex][1].keys():
            p = params.getByKey('w_'+str(nodeIndex)+'_'+str(neighborIndex))
            if neighborIndex < bestModel.numInputs:
              p = p*indepParamMax[neighborIndex]
            netList[nodeIndex][1][neighborIndex] = p
        #print netList
            
        return networkList2DOT(netList,bestModel.speciesNames,    \
                               bestModel.indepParamNames,filename,**kwargs)

    
class LaguerreFittingProblem(FittingProblem):
    """
    Parameters can vary with a single input as arbitrary polynomials.
    """
    def __init__(self,degreeList,fittingData,polynomialDegreeListList=None,     \
        indepParamsList=[[]],indepParamNames=[],outputName='output',            \
        degreeListNames=None,degreeListImages=None,avegtol=avegtolDefault,      \
        maxiter=maxiterDefault,singValCutoff=cutoffDefault,priorSigma=None,     \
        ensGen=None,verbose=verboseDefault,perfectModel=None,saveFilename=None, \
        bestSeenParamsDict={},                                                  \
        includeDerivs=False,useClampedPreminimization=False,                    \
        smallerBestParamsDict=None,saveKey=-1):
        
        if degreeListImages is None:
            degreeListImages = [ None for degree in degreeList ]
            
        if degreeListNames is None:
            degreeListNames = [ 'Degree '+str(degree)+' Laguerre polynomial'    \
                for degree in degreeList ]
        
        if polynomialDegreeListList is None:
            polynomialDegreeListList = [ None for degree in degreeList ]
        
        fittingModelList = [                                                    \
          LaguerreFittingModel(degree,outputName=outputName,                    \
            polynomialDegreeList=polynomialDegreeList,                          \
            indepParamNames=indepParamNames,image=image,                        \
            avegtol=avegtol,maxiter=maxiter,ensGen=ensGen,                      \
            verbose=verbose,                                                    \
            includeDerivs=includeDerivs,                                        \
            useClampedPreminimization=useClampedPreminimization)                \
          for degree,image,polynomialDegreeList in                              \
            zip(degreeList,degreeListImages,polynomialDegreeListList) ]
        
        # all daughter classes should call generalSetup
        self.generalSetup(fittingData,indepParamsList,indepParamNames,          \
            fittingModelList,singValCutoff,degreeListNames,verbose,perfectModel,\
            saveFilename,bestSeenParamsDict,                                    \
            smallerBestParamsDict,saveKey)
            
        self.convFlagDict = {}
    
    def fitAll(self,**kwargs):
        FittingProblem.fitAll(self,**kwargs)
        # we also want to save the convergence information in a
        # convenient location:
        for name in self.fittingModelNames:
            self.convFlagDict[name] = self.fittingModelDict[name].convFlag      

# 7.20.2009
class PolynomialFittingProblem(FittingProblem):
    """
    Parameters can vary with a single input as arbitrary polynomials.
    
    Directly copied from LaguerreFittingProblem
    """
    def __init__(self,degreeList,fittingData,polynomialDegreeListList=None,     \
        indepParamsList=[[]],indepParamNames=[],outputName='output',            \
        degreeListNames=None,degreeListImages=None,avegtol=avegtolDefault,      \
        maxiter=maxiterDefault,singValCutoff=cutoffDefault,priorSigma=None,     \
        ensGen=None,verbose=verboseDefault,perfectModel=None,saveFilename=None, \
        bestSeenParamsDict={},                                                  \
        includeDerivs=False,useClampedPreminimization=False,                    \
        smallerBestParamsDict=None,saveKey=-1):
        
        if degreeListImages is None:
            degreeListImages = [ None for degree in degreeList ]
            
        if degreeListNames is None:
            degreeListNames = [ 'Degree '+str(degree)+' polynomial'             \
                for degree in degreeList ]
        
        if polynomialDegreeListList is None:
            polynomialDegreeListList = [ None for degree in degreeList ]
        
        fittingModelList = [                                                    \
          PolynomialFittingModel(degree,outputName=outputName,                  \
            polynomialDegreeList=polynomialDegreeList,                          \
            indepParamNames=indepParamNames,image=image,                        \
            avegtol=avegtol,maxiter=maxiter,ensGen=ensGen,                      \
            verbose=verbose,includeDerivs=includeDerivs,                        \
            useClampedPreminimization=useClampedPreminimization)                \
          for degree,image,polynomialDegreeList in                              \
            zip(degreeList,degreeListImages,polynomialDegreeListList) ]
        
        # all daughter classes should call generalSetup
        self.generalSetup(fittingData,indepParamsList,indepParamNames,          \
            fittingModelList,singValCutoff,degreeListNames,verbose,perfectModel,\
            saveFilename,bestSeenParamsDict,                                    \
            smallerBestParamsDict,saveKey)
            
        self.convFlagDict = {}
    
    def fitAll(self,**kwargs):
        FittingProblem.fitAll(self,**kwargs)
        # we also want to save the convergence information in a
        # convenient location:
        for name in self.fittingModelNames:
            self.convFlagDict[name] = self.fittingModelDict[name].convFlag   


class FittingModel:
    """
    A general base class for a model that fits data.
    
    fittingData should be the same length as indepParamsList.
    """
    def fitToData(self,fittingData,indepParamsList,verbose=verboseDefault):
        print "Oops!  fitToData needs to be implemented!"
        raise Exception
        
    def currentCost(self,fittingData,indepParamsList):
        print "Oops!  currentCost needs to be implemented!"
        raise Exception
    
    def currentHessian(self,fittingData,indepParamsList):
        print "Oops!  currentHessian needs to be implemented!"
        raise Exception
        
    def plotResults(self,fittingData,indepParamsList):
        print "Oops!  plotResults needs to be implemented!"
        raise Exception
    
    def initializeParameters(self,paramList):
        print "Oops!  initializeParameters needs to be implemented!"
        raise Exception

    def evaluate(self,time,indepParams):
        print "Oops!  evaluate needs to be implemented!"
        raise Exception

    def evaluateVec(self,times,var,indepParams):
        print "Oops!  evaluateVec needs to be implemented!"
        raise Exception

class SloppyCellFittingModel(FittingModel):
    """
    A general SloppyCell Network that will be used to fit data
    under a set of experimental conditions.
    
    Uses Levenberg-Marquardt (Optimization.fmin_lm) to fit.
    
    (Note: SloppyCell uses the word "model" in a different way.)
    
    indepParamNames     : a list of names of (non-optimizable) 
                          independent parameters
    (as of 6.29.09, does not yet implement independent parameters)
    priorSigma          : if not None, priors that favor smaller
                          parameters are put uniformly on every
                          parameter (may want to make this more
                          general in the future)
    ensGen              : member of EnsembleGenerator class to use
                          for making an ensemble of parameter sets
                          used as starting points for local fits
    includeDerivs(False): if True, for every dynamic species (eg 'X1'), 
                          add a new assignment rule that keeps track 
                          of its derivative (eg 'ddt_X1')
                          
    """
    
    def __init__(self,SloppyCellNet,indepParamNames=[],image=None,              \
        avegtol=avegtolDefault,maxiter=maxiterDefault,priorSigma=None,          \
        ensGen=None,verbose=verboseDefault,                                     \
        includeDerivs=False,useClampedPreminimization=False,numprocs=1):
        # generalSetup should be run by all daughter classes
        self.generalSetup(SloppyCellNet,indepParamNames,image,avegtol,          \
            priorSigma,ensGen,verbose,includeDerivs,                            \
            useClampedPreminimization,numprocs)
            
    def generalSetup(self,SloppyCellNet,indepParamNames,image=None,             \
        avegtol=avegtolDefault,maxiter=maxiterDefault,priorSigma=None,          \
        ensGen=None,verbose=verboseDefault,                                     \
        includeDerivs=False,useClampedPreminimization=False,numprocs=1):
        self.net = SloppyCellNet
        if includeDerivs: # 9.2.2011
          for speciesName in self.net.rateRules.keys():
            rateRule = self.net.rateRules.getByKey(speciesName)
            defaultCompartment = self.net.species.values()[0].compartment
            self.net.addSpecies('ddt_'+speciesName,defaultCompartment)
            self.net.addAssignmentRule('ddt_'+speciesName,rateRule)
        self.initialParameters = self.getParameters()
        self.indepParamNames = indepParamNames
        self.image = image
        self.avegtol = avegtol
        self.maxiter = maxiter
        self.priorSigma = priorSigma
        self.ensGen = ensGen # ensemble generator
        self.verbose = verbose
        self.useClampedPreminimization = useClampedPreminimization
        self.numprocs = numprocs
        if not self.verbose:
            Utility.disable_debugging_msgs()
            Utility.disable_warnings()
        self.convFlag = None
        if self.indepParamNames == []:
            self.noIndepParams = True
        else:
            self.noIndepParams = False
        # 9.29.2011
        self.numCostCallsList = []
        self.numGradCallsList = []
        # 10.31.2011
        self.ensTimeSecondsList = []
        self.minimizationTimeSecondsList = []
            
        # 7.24.2009
        for name in indepParamNames:
            self.net.set_var_optimizable(name,False)
            
        # 7.31.2009
        self.maxMemoryUsage = maxMemoryUsageDefault
    
    def getParameters(self):
        return self.net.GetParameters()
        
    def initializeParameters(self,paramsKeyedList=[]):
        self.net.setOptimizables(self.initialParameters)
        if paramsKeyedList != []:
            self.net.setOptimizables(paramsKeyedList)
    
    def typicalIndepParamRanges(self,upperRangeMultiple=1.):
        """
        Returns the typical ranges of initial conditions for the 
        parameters in self.indepParamNames.  Useful when creating
        random initial conditions, or when calling 
        FittingProblem.outOfSampleCorrelation.
        
        upperRangeMultiple (1.)     : Each typical range is expanded by this
        factor by increasing the upper limit.
        """
        ranges = copy.copy( scipy.array(self.indepParamRanges) )
        rangeLengths = ranges[:,1]-ranges[:,0]
        
        ranges[:,1] = ranges[:,0] + upperRangeMultiple*rangeLengths
        
        return ranges
    
    def fitToData(self,fittingData,indepParamsList=[[]],                        \
        _unclampedSpeciesID=None,otherStartingPoint=None,                       \
        fittingDataDerivs=None,createEnsemble=True):
        """
        Generates an ensemble of parameter sets using ensemble
        generator self.ensGen, and uses each of these as a
        starting point for Levenberg-Marquardt.
        
        (If self.ensGen = None, finds best fit using LM from 
        initial parameters)
        
        fittingData should be a list of SloppyCell compatible
        data sets (dictionaries), and should be the same length 
        as indepParamsList (one set of data for each experimental 
        condition).
        
        If using clamped preminimization, currently assumes that the species
        with data are the same across different independent parameter
        conditions.  (As of 9.19.2012, clamped preminimization is 
        no longer actively supported)
        
        otherStartingPoint (None)      : Optionally provide a parameter set
                                         to replace the first ensemble
                                         starting point (EnsembleGenerator
                                         includes the initial parameters as
                                         the last ensemble starting point)
        fittingDataDerivs (None)       : Optionally provide time derivatives
                                         of all data points in fittingData,
                                         in which case we use log-linear 
                                         fitting (only works for 
                                         PowerLawFittingModel).  If provided,
                                         use different cost function (both
                                         for creating the ensemble and
                                         selecting the best model -- see
                                         notes 9/12/2012)
        createEnsemble (True)          : Calculate new ensemble even if there
                                         is already one stored.
        
        """
        if self.useClampedPreminimization and (_unclampedSpeciesID is None):
            # 10.3.2011 Fit clamped versions in succession to find good
            # starting place for full model parameters.  For each clamped
            # version, start over from the initial given parameters.
            originalInitialParams = self.getParameters()
            preClampCost = self.currentCost(fittingData,indepParamsList)
            allClampedParams = KeyedList()
            for speciesID in fittingData[0].keys():
              if self.verbose: print "SloppyCellFittingModel.fitToData: "       \
                "Clamped version, only fitting",speciesID,"..."
              self.initializeParameters(originalInitialParams)
              clampedParams = self.fitToData(fittingData,indepParamsList,       \
                _unclampedSpeciesID=speciesID)
              for paramName,paramValue in clampedParams.items():
                if not allClampedParams.has_key(paramName):
                  allClampedParams.setByKey(paramName,[])
                allClampedParams.getByKey(paramName).append(paramValue)
            # use average value of all seen fit values for each parameter
            averageClampedParams = KeyedList()
            for paramName,paramValueList in allClampedParams.items():
              averageClampedParams.setByKey(paramName,scipy.mean(paramValueList))
            # 10.3.2011 ******************
            if self.verbose: print "SloppyCellFittingModel.fitToData: "         \
                "allClampedParams =",allClampedParams
            if self.verbose: print "SloppyCellFittingModel.fitToData: "         \
                "averageClampedParams =",averageClampedParams
            # ****************************
            self.initializeParameters(averageClampedParams)
            
            # 10.31.2011 check that clamping hasn't made the fit worse
            postClampCost = self.currentCost(fittingData,indepParamsList)
            if postClampCost > preClampCost:
                if self.verbose: print "SloppyCellFittingModel.fitToData: "     \
                    "clampedParams are worse than initial ones.  "              \
                    "Using initial parameters."
                self.initializeParameters(originalInitialParams)
        
        if (self.ensGen != None) or (fittingDataDerivs is None):
          dataModel = self._SloppyCellDataModel(fittingData,indepParamsList,    \
            unclampedSpeciesID=_unclampedSpeciesID,                             \
            fittingDataDerivs=fittingDataDerivs,                                \
            disableIntegration=(fittingDataDerivs is not None))
        if _unclampedSpeciesID is not None:
            # 10.3.2011 temporarily replace self.net with version with
            # fewer optimizable parameters
            originalNet = self.net.copy()
            self.net = dataModel.get_calcs()[0]
        
        # make ensemble
        initialParameters = self.getParameters()
        # 10.3.2011 *************************
        if self.verbose: print "SloppyCellFittingModel.fitToData: "             \
            "generating ensemble for these parameters:",initialParameters.keys()
        # ***********************************
        if hasattr(self,'ensemble') and (not createEnsemble):
            ens = self.ensemble
            ratio = self.acceptanceRatio
            if self.verbose: print "SloppyCellFittingModel.fitToData: "         \
                "using ensemble stored in self.ensemble."
        elif self.ensGen != None:
            startTimeEns = time.clock()
            if self.numprocs > 1:
                ens,ratio = self.ensGen.generateEnsemble_pypar(self.numprocs,   \
                    dataModel,initialParameters)
            else:
                ens,ratio = self.ensGen.generateEnsemble(dataModel,             \
                    initialParameters)
            if ens == [[]]: # 5.16.2012 we had weird error (see notes)
                print "SloppyCellFittingModel.fitToData: Ensemble generation "  \
                      "failed.  Using self.initialParameters."
                ens = [self.initialParameters]
            ensTimeSeconds = time.clock() - startTimeEns
            self.ensTimeSecondsList.append(ensTimeSeconds)
        else:
            ens = [initialParameters]
            ratio = None
            
        # 4.17.2012
        if otherStartingPoint is not None:
            # ********
            print "SloppyCellFittingModel.fitToData: Using otherStartingPoint"
            #print "         with parameters",otherStartingPoint
            # ********
            if len(ens) == 1: # 5.16.2012 we had weird error (see notes)
                ens = [otherStartingPoint,ens[0]]
            else:
                ens[0] = otherStartingPoint
        self.acceptanceRatio = ratio
        self.ensemble = ens
        self.ensembleAfterFit = []
    
        # 5.1.2013 warn if acceptance ratio is small
        if self.acceptanceRatio < 1./len(self.ensemble):
            print "SloppyCellFittingModel.fitToData: WARNING: "                 \
                "Small ensemble acceptance ratio ("+str(self.acceptanceRatio)+")"
        
        bestCost = scipy.inf
        bestParams = initialParameters
        bestConvFlag = None
        bestIndex = None
        
        if (self.numprocs == 1) or fittingDataDerivs is not None: # don't run in parallel
          self.numCostCallsList,self.numGradCallsList = [],[]
          self.minimizationTimeSecondsList = []
          self.convFlagList,self.costList = [],[]
          for index,params in enumerate(ens):
            #self.initializeParameters(params)
            startTime = time.clock()
            
            if fittingDataDerivs is None:
              fitParams,convFlag,cost,numCostCalls,numGradCalls,Lmbda,j =       \
                self.localFitToData(fittingData,dataModel,retall=True,          \
                startParams=params)
            else: # 8.30.2012 XXX have arguments come from elsewhere
              print "SloppyCellFittingModel.fitToData: Calling fitToDataDerivs"
              self.initializeParameters(params)
              fitParams,afterMinCostList,afterExpCostList,convFlag =            \
                    self.fitToDataDerivs(fittingData,fittingDataDerivs,         \
                        indepParamsList,numLinearIter=10,verbose=True,          \
                        maxiter=1,retall=True)
              numCostCalls,numGradCalls = 0,0
              if not hasattr(self,'afterMinCostDict'):
                  self.afterMinCostDict,self.afterExpCostDict = {},{}
              self.afterMinCostDict[index] = afterMinCostList
              self.afterExpCostDict[index] = afterExpCostList
            
            minimizationTimeSeconds = time.clock() - startTime
            self.minimizationTimeSecondsList.append(minimizationTimeSeconds)
            
            if fittingDataDerivs is not None:
                try:
                    fitCost = self.currentCost_deriv(fittingData,           \
                        indepParamsList,fittingDataDerivs)
                except OverflowError:
                    fitCost = scipy.inf
            else:
                # usual case
                try:
                    fitCost = dataModel.cost(fitParams)
                except (Utility.SloppyCellException,OverflowError):
                    fitCost = scipy.inf
            
            print "Cost: ",fitCost,"(",convFlag,")"
            self.ensembleAfterFit.append(fitParams)
            self.numCostCallsList.append(numCostCalls)
            self.numGradCallsList.append(numGradCalls)
            self.convFlagList.append(convFlag)
            self.costList.append(fitCost)
            if fitCost <= bestCost: # 1.23.2013 changed from < to <=
                bestIndex = index
                bestCost = fitCost
                bestParams = fitParams
                bestConvFlag = convFlag
        else: # run in parallel 3.21.2012
            outputDict = self.localFitToData_pypar(self.numprocs,fittingData,   \
                dataModel,ens,indepParamsList)
            indices = scipy.sort(outputDict.keys())
            self.costList = [ outputDict[i][2] for i in indices ]
            bestIndex = scipy.argsort(self.costList)[0]
            bestCost = self.costList[bestIndex]
            bestParams = outputDict[bestIndex][0]
            bestConvFlag = outputDict[bestIndex][1]
            self.convFlagList = [ outputDict[i][1] for i in indices ]
            self.numCostCallsList = [ outputDict[i][3] for i in indices ]
            self.numGradCallsList = [ outputDict[i][4] for i in indices ]
            self.minimizationTimeSecondsList =                                  \
                                    [ outputDict[i][7] for i in indices ]
            self.ensembleAfterFit = [ outputDict[i][0] for i in indices ]
        
        print "Best-fit cost: ",bestCost
        self.bestParams = bestParams
        self.net.setOptimizables(bestParams)
        self.convFlag = bestConvFlag
        self.bestIndex = bestIndex
        if _unclampedSpeciesID is not None:
            # restore original full network
            self.net = originalNet
        return bestParams
        
    def localFitToData(self,fittingData,dataModel,retall=False,startParams=None):
        """
        Uses Levenberg-Marquardt to find local best fit.
        """
        if startParams is not None:
            self.initializeParameters(startParams)
            
        initialParameters = self.getParameters()
        minimizerList = []
        #dataModel = self._SloppyCellDataModel(fittingData,indepParamsList)
        if hasattr(self,'minimizeInLog'):
          if self.minimizeInLog:
            minimizerList.append( Optimization.fmin_lm_log_params )
        else:
            minimizerList.append( Optimization.fmin_lm )
        
        for minimizer in minimizerList:
            try:
              fitParameters,cost,numCostCalls,numGradCalls,convFlag,Lmbda,j =       \
                minimizer(                                                          \
                    dataModel,initialParameters,                                    \
                    avegtol=self.avegtol,maxiter=self.maxiter,full_output=True,     \
                    disp=self.verbose,maxMemoryUsage=self.maxMemoryUsage)
              print "localFitToData: Cost =",cost
            except KeyboardInterrupt:
              raise
            # 3.21.2012 commented this out for debugging.  
            except:
              print "FittingProblem localFitToData:"
              print "     Warning: Minimization failed. (flag 5)"
              fitParameters = initialParameters
              convFlag = 5
              cost = scipy.inf
              numCostCalls,numGradCalls = scipy.nan,scipy.nan
              Lmbda,j = None,None
            initialParameters = fitParameters
              
        self.net.setOptimizables(fitParameters)
        fitParameters = self.getParameters() # so it's a keyed list
        #self.convFlag = convFlag
        if retall:
            return fitParameters,convFlag,cost,numCostCalls,numGradCalls,Lmbda,j
        else:
            return fitParameters,convFlag
    
    # 3.21.2012
    def localFitToData_pypar(self,numprocs,fittingData,dataModel,startParamsList,indepParamsList):
        """
        Uses pypar to run many local fits (localFitToData) in parallel.
        """
        
        scipy.random.seed()
        prefix = "temporary_" + str(scipy.random.randint(1e8))                  \
            + "_localFitToData_pypar_"
        inputDictFilename = prefix + "inputDict.data"
        outputFilename = prefix + "output.data"
        inputDict = { 'fittingProblem':self,
                      'fittingData':fittingData,
                      'dataModel':dataModel,
                      'startParamsList':startParamsList,
                      'outputFilename':outputFilename,
                      'indepParamsList':indepParamsList }
        save(inputDict,inputDictFilename)
        
        # call mpi
        stdoutFile = open(prefix+"stdout.txt",'w')
        call([ "mpirun","-np",str(numprocs),"python","localFitParallel.py",     \
              inputDictFilename ], stderr=stdoutFile,stdout=stdoutFile)
        stdoutFile.close()
        os.remove(inputDictFilename)

        try:
            output = load(outputFilename)
            os.remove(outputFilename)
            os.remove(prefix+"stdout.txt")
        except IOError:
            print "localFitToData_pypar error:"
            stdoutFile = open(prefix+"stdout.txt")
            stdout = stdoutFile.read()
            print stdout
            os.remove(prefix+"stdout.txt")
            raise Exception, "localFitToData_pypar:"                            \
                + " error in localFitParallel.py"

        return output
                
    def currentCost(self,fittingData,indepParamsList=[[]],includePriors=True,   \
        fittingDataDerivs=None,**kwargs):
        # 12.13.2012 added disableIntegration when fittingDataDerivs is given
        if includePriors:
          # 3.29.2012 In this function (and in currentHessian 
          #     and currentHessianNoPriors below) I played around
          #     with storing a copy of dataModel and dataModelNoPriors,
          #     but this turned out to make the fittingProblem instance
          #     huge to store on disk.  Note that in the current way the
          #     fitting procedure is implemented, we do NOT call
          #     currentCost every time, but instead make a dataModel
          #     that we use until done fitting (so we don't get a 
          #     speedup in fitting by storing a dataModel here, as
          #     I had hoped).
          #if not hasattr(self,'dataModel'):
          #  self.dataModel = self._SloppyCellDataModel(fittingData,indepParamsList)
          #dataModel = self.dataModel
          dataModel = self._SloppyCellDataModel(fittingData,indepParamsList,    \
                fittingDataDerivs=fittingDataDerivs,**kwargs)
        else:
          #if not hasattr(self,'dataModelNoPriors'):
          #  self.dataModelNoPriors = self._SloppyCellDataModel(                \
          #      fittingData,indepParamsList,includePriors=False)
          #dataModel = self.dataModelNoPriors
          dataModel = self._SloppyCellDataModel(fittingData,indepParamsList,    \
              includePriors=False,fittingDataDerivs=fittingDataDerivs,**kwargs)

        return dataModel.cost(self.getParameters())
        
    def currentHessian(self,fittingData,indepParamsList=[[]],                   \
        fittingDataDerivs=None,**kwargs):
        """
        Returns JtJ, an approximation of the Hessian that uses
        analytical derivatives.
        """
        dataModel = self._SloppyCellDataModel(fittingData,indepParamsList,      \
            fittingDataDerivs=fittingDataDerivs,**kwargs)
        J,JtJ = dataModel.GetJandJtJ(self.getParameters())
        return JtJ
        
    def currentHessianNoPriors(self,fittingData,indepParamsList=[[]],           \
        fittingDataDerivs=None,**kwargs):
        """
        Returns JtJ, an approximation of the Hessian that uses
        analytical derivatives.  (does not put on priors)
        """
        dataModelNoPriors = self._SloppyCellDataModel(                          \
            fittingData,indepParamsList,includePriors=False,                    \
            fittingDataDerivs=fittingDataDerivs,**kwargs)
        J,JtJ = dataModelNoPriors.GetJandJtJ(self.getParameters())
        return JtJ
    
    # 5.2.2013
    def currentHessianNoData(self,fittingData,indepParamsList=[[]],**kwargs):
        """
        Returns JtJ, an approximation of the Hessian that uses
        analytical derivatives.  (includes no data, only priors)
        
        (Bug: Shouldn't have to pass fittingData and indepParamsList, I think,
        but I can't get _SloppyCellDataModel to work otherwise.)
        """
        modelNoData = self._SloppyCellDataModel(                                \
            fittingData,indepParamsList,includePriors=True,includeData=False,   \
            **kwargs)
        J,JtJ = modelNoData.GetJandJtJ(self.getParameters())
        return JtJ
    
    def plotResults(self,fittingData,indepParamsList=[[]],                      \
        show_legend=False,numPoints=500,errorBars=True,exptsToPlot=None,        \
        dataToPlot=None,numRows=None,fmt=None,plotHiddenNodes=True,             \
        separateIndepParams=True,figHeight=8,figWidth=None,newFigure=True,      \
        rowOffset=0,                                                            \
        plotDerivs=False,linestyle=None,plotInitialConditions=False,            \
        marker=None,numCols=None,xmax=None,color=None,**kwargs):
        """
        Note: exptsToPlot isn't currently used when numCols != 1.
        
        separateIndepParams (True)      : 4.18.2012 plot each set of independent
                                          parameters and each species in a 
                                          separate subplot
        numCols (None)                  : 4.17.2013 if set to 1, use a single
                                          column for all independent parameters
        """
        
        
        
        dataModel = self._SloppyCellDataModel(fittingData,indepParamsList)
        # may not need the following line if cost has already been evaluated
        dataModel.cost(self.getParameters())
        
        calcColl = dataModel.GetCalculationCollection()
        
        # Get the time endpoints over which we want to integrate.
        # (there may be a better way to do this...)
        # 3.30.2012 Use the union of ranges that have been used for all vars.
        timeEndpoints = [0.,0.]
        for net in calcColl.values():
            traj = getattr(net, 'trajectory')
            timeEndpoints[0] = min(min(traj.timepoints),timeEndpoints[0])
            timeEndpoints[1] = max(max(traj.timepoints),timeEndpoints[1])
            
        for net in calcColl.values():
            # Explicitly include a lot of time points so we're sure to
            # get nice smooth-looking curves.
            times = scipy.linspace(timeEndpoints[0],timeEndpoints[-1],numPoints)
            traj = Dynamics.integrate(net,times,return_derivs=True) #was net.integrate(times)
            net.trajectory = traj
            
        # 4.18.2012
        netIDList = [ self._SloppyCellNetID(ip) for ip in indepParamsList ]
        
        style = 'errorbars'
            
        if (numRows == None) and (not separateIndepParams): 
            # plot everything on one subplot
            return Plotting.plot_model_results(dataModel,                       \
                show_legend=show_legend,style=style,expts=exptsToPlot,          \
                data_to_plot=dataToPlot,**kwargs)
        else:
            # assumes first dataset includes all species of interest
            varsWithData = fittingData[0].keys()
            if dataToPlot is None:
                # sort in the order they're found in self.speciesNames
                dataToPlotSorted = []
                for name in self.speciesNames:
                    if plotDerivs: fullName = (name,'time')
                    else: fullName = name
                    if name in varsWithData: dataToPlotSorted.append(fullName)
                    elif plotHiddenNodes: dataToPlotSorted.append(fullName)
            else:
                dataToPlotSorted = dataToPlot
                
            cW = Plotting.ColorWheel()
            #if separateIndepParams:
            if numRows is None:
                numRows = len(dataToPlotSorted)
            if numCols is None:
                numCols = len(indepParamsList)
                
            # set up figure
            aspectRatioIndiv = (1. + scipy.sqrt(5))/2.
            if separateIndepParams and newFigure:
                indivHeight = float(figHeight)/float(numRows)
                if figWidth is None:
                    figWidth = aspectRatioIndiv*indivHeight*numCols
                Plotting.figure(figsize=(figWidth,figHeight))
                pad = 0.1*8./figWidth # want default (0.1) when figWidth is default (8.)
                Plotting.subplots_adjust(wspace=0.,hspace=0.05,left=pad,right=1.0-pad)
            
            returnList = []
            
            # loop over species
            for i,name in enumerate(dataToPlotSorted):
              
              ymins,ymaxs = [],[]
              axList = []
              
              # increment colors
              if fmt is None:
                if name in varsWithData:
                    colorWheelFmt = cW.next()
                else: # 3.30.2012 plot hidden nodes gray by default
                    colorWheelFmt = 'gray','o','-'
              else:
                colorWheelFmt = fmt
              if color is not None:
                colorWheelFmt = color,colorWheelFmt[1],colorWheelFmt[2]
              if linestyle is not None:
                colorWheelFmt = colorWheelFmt[0],colorWheelFmt[1],linestyle
              if marker is not None:
                colorWheelFmt = colorWheelFmt[0],marker,colorWheelFmt[2]
                
              # loop over independent parameter conditions
              for j,netID in enumerate(netIDList):
                    
                if separateIndepParams:
                    if numCols == 1:
                        subplotIndex = 1+(i+rowOffset)*numCols
                    else:
                        subplotIndex = (j+1)+(i+rowOffset)*numCols
                    ax = Plotting.subplot(numRows,numCols,subplotIndex)
                    
                    # Mess with ticks
                    # wider tick spacing
                    numticks = 3
                    ax.yaxis.set_major_locator(Plotting.matplotlib.ticker.LinearLocator(numticks=numticks))
                    # remove middle y axes labels
                    if (j != 0) and (numCols>1): 
                        ax.get_yaxis().set_ticklabels([])
                    # remove middle x axes labels
                    if i != len(dataToPlotSorted)-1: 
                        ax.get_xaxis().set_ticklabels([])
                    
                else: 
                    ax = Plotting.subplot(numRows,numCols,i+1)
                axList.append(ax)
                
                returnList.append( Plotting.plot_model_results(dataModel,       \
                    show_legend=show_legend,style=style,                        \
                    colorWheelFmt=colorWheelFmt,data_to_plot=[name],            \
                    expts=['data'+netID],plot_data=errorBars,**kwargs) )
    
                if plotInitialConditions and (i<len(indepParamsList[j])):
                    Plotting.plot([0],[indepParamsList[j][i]],                  \
                        marker=colorWheelFmt[1],color=colorWheelFmt[0])
                
                if j == 0:
                    Plotting.ylabel(name)
                
                ranges = Plotting.axis()
                ymins.append(ranges[2])
                ymaxs.append(ranges[3])
                
                if i == len(dataToPlotSorted)-1:
                    # remove last x tick label to prevent overlap
                    # this doesn't work because the labels don't yet exist
                    #xtl = [ t.get_text() for t in ax.xaxis.get_ticklabels() ]
                    #if xtl[-1] == '': xtl[-2] = ''
                    #else: xtl[-1] = ''
                    #ax.xaxis.set_ticklabels(xtl)
                    xticks = ax.xaxis.get_ticklocs()
                    ax.xaxis.set_ticks(xticks[:-1])
                
              if xmax is not None:
                Plotting.axis(xmax=xmax)
              
              if separateIndepParams:
                # make y axes have same range
                [ ax.axis(ymin=min(ymins),ymax=max(ymaxs)) for ax in axList ]
                
                # remove last y tick label to prevent overlap
                # this doesn't work because the labels don't yet exist
                ax0 = axList[0]
                
                yticks = ax0.yaxis.get_ticklocs()
                #print "yticks =",yticks
                ax0.yaxis.set_ticks(yticks[:-1])
                #print "ytl =", ytl
                
            return returnList
    
    # 9.26.2012
    def plotDerivResults(self,fittingData,fittingDataDerivs,
        indepParamsList=[[]],newFigure=True,marker='o'):
        """
        Plot showing how well you're doing at fitting the function that
        takes current values to current derivatives.
        
        (I think assumes that the model made by _SloppyCellDataModel does
        not include any scale_factors that aren't 1.)
        """
        dataModel = self._SloppyCellDataModel(fittingData,indepParamsList,      \
            fittingDataDerivs=fittingDataDerivs,includePriors=False,            \
            disableIntegration=(fittingDataDerivs is not None))
        
        # evaluate the model at current parameters
        dataModel.CalculateForAllDataPoints(self.getParameters())
        calcVals = dataModel.GetCalculatedValues()
        
        # () loop over residuals in SloppyCellDataModel
        predictedVals,dataVals,dataSigmas = [],[],[]
        for r in dataModel.residuals:
            predictedVals.append( calcVals[r.calcKey][r.yKey][r.xVal] )
            dataVals.append( r.yMeas )
            dataSigmas.append( r.ySigma )
        
        # () make plot
        if newFigure: pylab.figure()
        pylab.errorbar(dataVals,predictedVals,xerr=dataSigmas,ls='',            \
            marker=marker)
            
        # () plot diagonal
        maxVal = max(max(dataVals),max(predictedVals))
        minVal = min(min(dataVals),min(predictedVals))
        pad = 0.1*(maxVal-minVal)
        minPad,maxPad = minVal-pad,maxVal+pad
        pylab.plot([minPad,maxPad],[minPad,maxPad],'k-')
        pylab.axis([minPad,maxPad,minPad,maxPad])
        
        # () axis labels
        pylab.xlabel('Measured time derivative')
        pylab.ylabel('Predicted time derivative')
        
        return dataVals,predictedVals
    
    def evaluate(self,time,var,indepParams):
        #net = self._SloppyCellNet(indepParams) # slow
        for name,value in zip(self.indepParamNames,indepParams):
            self.net.setInitialVariableValue(name,value)
        traj = Dynamics.integrate(self.net,[0.,time],return_derivs=True)
        return traj.get_var_val(var,time)
        
    # 1.24.2013
    def setInitialVariables(self,indepParams):
        for name,value in zip(self.indepParamNames,indepParams):
            self.net.setInitialVariableValue(name,value)
        
    def evaluateVec(self,times,var,indepParams,defaultValue=0.):
        """
        var can be a single variable name or list of variable names.
        
        In the case of an exception (a problem with the integration), 
        returns the defaultValue for all times.
        
        Use the format (varName,'time') for the time derivative
        of a variable.
        """
        #net = self._SloppyCellNet(indepParams) # slow
        self.setInitialVariables(indepParams)
        
        try:
            singleVariable = isinstance(var,tuple) or ( len(scipy.shape(var)) == 0 )
        except: # scipy.shape dies if there are tuples and strings
            singleVariable = False 
        try:
            #traj = self.net.integrate(scipy.array( [0.]+list(times) ))
            eps = 1e-5 # in case you only want t=0, which SloppyCell doesn't like
            allTimes = scipy.sort( [0.]+list(times)+[eps] )
            traj = Dynamics.integrate(self.net, allTimes, return_derivs=True)
        except Utility.SloppyCellException:
            print "SloppyCellFittingModel.evaluateVec: "                                \
                  "WARNING: Exception in integration. "                                 \
                  "Returning default value for all requested times."
            if singleVariable: 
                return scipy.array([ defaultValue for time in times ])
            else: 
                return scipy.array([ [ defaultValue for time in times ] for v in var ])
    
        for time in times:
            if time not in traj.get_times(): raise Exception
    
        if singleVariable: 
            return scipy.array([ traj.get_var_val(var,time) for time in times ])
        else:
            return scipy.array([                                                        \
                [ traj.get_var_val(v,time) for time in times ] for v in var ])
    
    def _SloppyCellNet(self,indepParams=[]):
        """
        Returns SloppyCell network with the given independent parameters.
        """
        newNet = self.net.copy()
        
        if not self.noIndepParams:
            # we do have independent parameters to set
            newNet.set_id(self._SloppyCellNetID(indepParams))
            for name,value in zip(self.indepParamNames,indepParams):
                newNet.setInitialVariableValue(name,value)
        
        return newNet
        
    def _SloppyCellNetID(self,indepParams):
        indepParamsID = str(zip(self.indepParamNames,indepParams))          \
            .replace("'","").replace(" ","").replace(",","_")               \
            .replace(".","_").replace("[","_").replace("]","_")             \
            .replace("(","_").replace(")","_")
        if len(indepParamsID) > 50: # can't have overly long file names
            # Let's pray we don't have hash conflicts.
            # If we ever do, SloppyCell should complain that
            # we're trying to create something with the same name.
            indepParamsID = str(hash(indepParamsID))
        return self.net.get_id()+indepParamsID
                
    def _SloppyCellDataModel(self,data,indepParamsList=[[]],exptID='data',      \
        includePriors=True,unclampedSpeciesID=None,removeLogForPriors=True,     \
        fittingDataDerivs=None,disableIntegration=True,includeData=True):
        """
        Returns SloppyCell 'model' that contains the given network
        and the given data (also setting fixed scale factors).
        
        Here the data should be the output of PerfectData.discrete_data 
        (or a list of such data sets corresponding to the independent
        parameters listed in indepParamsList).
        
        Note that the names of the species given in the data should 
        match names of species in the model.
        
        unclampedSpeciesID (None)       : if not None, "clamps" all species except 
                                          unclampedSpeciesID to the given data.
                                          (Hopefully useful for faster 
                                          minimization in large models with 
                                          data for lots of species.)
        removeLogForPriors (True)       : If a parameter name starts with "log",
                                          use GaussianPriorExp
        fittingDataDerivs (None)        : see notes 9/14/2012
        disableIntegration (True)       : Only used when fittingDataDerivs is given.
                                          If True, zero all visible species 
                                          (but not their derivatives, which are 
                                          calculated using fittingData).  
                                          Probably a bad idea if you have hidden
                                          species.
                                          
        4.29.2013 self.priorSigma can be a list of length 2 tuples of the form
        (n,sigma_n), where n is a string specifying the beginning of the desired
        parameters' names (eg 'w' specifies 'w_0' and 'w_1' and 'w_self'), and
        sigma_n is the desired prior sigma.
        
        11.29.2012 ***BUG: No species names in fittingDataDerivs is allowed
        to be contained within any other (later) species name.
        
        """
        exptList = []
        netList = []
        
        # make a copy
        # of the SloppyCell network for each experimental condition
        for i,indepParams,d in zip(range(len(data)),indepParamsList,data):
            newNet = self._SloppyCellNet(indepParams)
            newNetID = newNet.get_id()
            newExpt = Experiment(exptID+newNetID)
            
            rateRulesBefore = Utility.copy.copy(self.net.rateRules)
            # 12.6.2012 optionally disable full integration by
            # removing non-differentiated variables
            if disableIntegration and (fittingDataDerivs is not None):
                # set rates to zero, remove dynamic variables and
                # things that refer to them, and add a dummy
                # dynamic variable
                keyList = d.keys()
                for visibleSpecies in d.keys():
                    newNet.addRateRule(visibleSpecies,'0.')
                for visibleSpecies in d.keys():
                    newNet.remove_component(visibleSpecies) #XXXXX
                    newNet.remove_component('ddt_'+visibleSpecies)
                dName = 'dummy_variable'
                newNet.addSpecies(dName,newNet.compartments.keys()[0],'0.')
                newNet.addRateRule(dName,'0.')
                newNet.compile()
            
            if fittingDataDerivs is None:
                exptData = d
            else: # 9.14.2012 derivative data (for powerLaw log-linear fitting)
                exptData = {}
                uniqueID = 0
                # for each data point, add a variable that calculates that derivative
                for speciesName in d.keys()[::-1]: 
                  for time in d[speciesName].keys():
                    uniqueID += 1
                    valueName = speciesName+'_deriv_'+str(uniqueID)
                    # add species that will calculate model value
                    defaultCompartment = newNet.species.values()[0].compartment
                    newNet.addSpecies(valueName,defaultCompartment)
                    rateRule = rateRulesBefore.getByKey(speciesName)
                    # set visible species to known values
                    # 11.29.2012 [::-1] = quick hack for bug
                    for visibleSpecies in d.keys()[::-1]: 
                      curVal = d[visibleSpecies][time][0]
                      rateRule = rateRule.replace(visibleSpecies,str(curVal))
                    newNet.addAssignmentRule(valueName,rateRule)
                    # add given derivative data
                    exptData[valueName] = fittingDataDerivs[i][speciesName]

              
            # 10.3.2011 'clamp' option
            # (do we want to modify d to not include the clamped variables?)
            if unclampedSpeciesID is not None:
                newNet = self._SloppyCellNetClamped(newNet,                     \
                    unclampedSpeciesID,d)
                
            newExpt.update_data({newNetID: exptData})
            newExpt.set_fixed_sf( dict( [(speciesName, 1.)                      \
                for speciesName in newNet.species.keys()] ))
            netList.append(newNet)
            exptList.append(newExpt)
    
        if includeData: # usual case
            m = Model(exptList,netList)
        else: # 5.2.2013 used when you only want priors
            m = Model([],[])
        
        # add priors
        if (self.priorSigma != None) and includePriors:
            for paramName in netList[0].GetParameters().keys(): #self.getParameters().keys()
                # Get width of prior from self.priorSigma
                # 4.29.2013 priorSigma can be a list of length 2 tuples
                if type(self.priorSigma) == list:
                    l = filter(lambda n: paramName.startswith(n[0]),            \
                               self.priorSigma)
                    if len(l) < 1:
                        raise Exception,"No matching prior for "+str(paramName)
                    elif len(l) > 1:
                        raise Exception,                                        \
                            "Multiple matching priors for "+str(paramName)
                    else:
                        sigma = l[0][1]
                else:
                    sigma = self.priorSigma
                
                # Create and add SloppyCell prior
                if removeLogForPriors and (paramName[:4]=="log_"):
                    res = GaussianPrior.GaussianPriorExp('%s_prior' % paramName,\
                        paramName, 0., sigma)
                else:
                    res = GaussianPrior.GaussianPrior('%s_prior' % paramName,   \
                        paramName, 0., sigma)
                m.AddResidual(res)
        
        return m
        
    # 9.30.2011
    def _SloppyCellNetClamped(self,net,unclampedSpeciesID,data):
        """
        Modifies given SloppyCell net to "clamp" all species 
        except unclampedSpeciesID to the given data.
        
        Hopefully useful for faster minimization in large models
        with data for lots of species.
        
        Makes unused parameters non-optimizable.
        
        data = single SloppyCell data structure (not including
               multiple independent parameter conditions)
        """
        
        # make a modified version of self.net that has everything clamped
        clampedNet = net.copy()
        
        eventDict = {}
        # for any species with data that's not unclampedSpeciesID...
        for dataSpeciesID in data.keys():
          if dataSpeciesID != unclampedSpeciesID:
            
            # ...add events that update the clamped variables...
            speciesData = data[dataSpeciesID].items()
            speciesData.sort() # time order
            speciesDataTimes = [ dataPoint[0] for dataPoint in speciesData ]
            speciesDataVals = [ dataPoint[1][0] for dataPoint in speciesData ]
            #interpFn = scipy.interpolate.interp1d(                          \
            #    speciesDataTimes,speciesDataVals,**interpKwargs)
            #interpFn = self._interpolatePiecewiseRHS(speciesDataTimes,      \
            #    speciesDataVals)
            # keep track of event times in a dictionary so that we don't
            # unneccessarily have multiple events for a single time
            
            for i in range(len(speciesDataTimes)):
                if i==0:
                  midpointTimeBefore = 0. # assuming everything starts at 0
                else:
                  midpointTimeBefore =                                      \
                    0.5*(speciesDataTimes[i-1]+speciesDataTimes[i])
                eventTrigger = "gt(time,"+str(midpointTimeBefore)+")" #geq(
                if not eventDict.has_key(eventTrigger):
                    eventDict[eventTrigger] = {}
                val = speciesDataVals[i]
                eventDict[eventTrigger].update({dataSpeciesID: val})
                #clampedNet.add_event(id,"gt(time,"+str(time)+")",           \
                #    {dataSpeciesID: val})

            # ...and remove old rule.
            if dataSpeciesID in clampedNet.rateRules.keys():
                clampedNet.rateRules.removeByKey(dataSpeciesID)
            if dataSpeciesID in clampedNet.assignmentRules.keys():
                clampedNet.assignmentRules.removeByKey(dataSpeciesID)

            # (add assignment rule _before_ the rest)
            #clampedNet.assignmentRules.insert_item(0,dataSpeciesID,interpFn)
            #clampedNet._makeCrossReferences()
            #clampedNet.updateAssignedVars(time=0)
            
            clampedNet.setInitialVariableValue(dataSpeciesID,0.)
            
        # add the events
        for eventTrigger,assignmentDict in eventDict.items():
            id = eventTrigger
            clampedNet.add_event(id,eventTrigger,assignmentDict)
        
        # make unused parameters unoptimizable so we won't try to fit them
        unusedVariables = self._findUnusedVariables(clampedNet,data)
        for unused in unusedVariables:
            #print "Removing",unused,"..."
            clampedNet.set_var_optimizable(unused,False)
            
        return clampedNet
                
        
    # 9.30.2011
    def _findUsedVariables(self,net,data):
        """
        Find all variable names used to calculate the variables in data.keys()
        in the given SloppyCell network 'net'.
        """
        usedVariables = sets.Set(data.keys())
        compList = [net.functionDefinitions,net.constraints,                    \
            net.assignmentRules,net.rateRules,net.algebraicRules]
        
        # iteratively see what we need to calculate each variable
        oldLen = -1
        while len(usedVariables) > oldLen:
          oldLen = len(usedVariables)
          for comp in compList:
            for id,expr in comp.items():
              if id in usedVariables:
                usedVariables.union_update(ExprManip.extract_vars(expr))
          # include initial values
          usedVarsSoFar = tuple(usedVariables)
          for var in net.variables.keys(): #usedVarsSoFar: # XXX why doesn't this work?  are we including too many initial variables as optimizable?
            initVarExpr = net.getInitialVariableValue(var)
            #if type(initVarExpr)==str:  
            usedVariables.union_update(ExprManip.extract_vars(initVarExpr))
        return usedVariables
        
    # 9.30.2011
    def _findUnusedVariables(self,net,data):
        """
        Find all variable names NOT used to calculate the variables in data.keys()
        in the given SloppyCell network 'net'.
        """
        usedVariables = self._findUsedVariables(net,data)
        allVariables = set(net.optimizableVars.keys())
        unusedVariables = allVariables.difference(usedVariables)
        return unusedVariables
        
    # 10.1.2011
    # no longer used as of 10.2.2011
    def _interpolatePiecewiseRHS(self,xvals,yvals,xVar='time'):
        """
        Returns string that evaluates to a piecewise interpolating
        function using the given xvals and yvals.
        
        The current default for extrapolation outside the given range
        is to stay constant at the boundary's value.
        
        xvals should be sorted by size!
        
        (Assumes 'time' variable is given as a single value, not
        as an array)
        """
        
        xStr = xVar #"scipy.array(["+xVar+"],float)" # 'scipy.array(['?
        string = "piecewise("
        #condlistStr = "["
        #funclistStr = "["
        
        # less than xvals[0]
        string += str(yvals[0])+","
        string += "lt("+xStr+","+str(xvals[0])+"),"
        
        for x0,x1,y0,y1 in zip(xvals[:-1],xvals[1:],yvals[:-1],yvals[1:]):
            x0,x1,y0,y1 = str(x0),str(x1),str(y0),str(y1)
            #condlistStr += "scipy.logical_and("+xStr+">="+x0+","+xStr+"<="+x1+"),"
            #funclistStr += "lambda t: "+y0+" + "                            \
            #    +"("+y1+"-"+y0+")/("+x1+"-"+x0+")*(t-"+x0+"),"
            string += y0+" + "+"("+y1+"-"+y0+")/("+x1+"-"+x0+")*("+xStr+"-"+x0+"),"
            string += "and_func(geq("+xStr+","+x0+"), leq("+xStr+","+x1+")),"
            
        # greater than xvals[-1]
        string += str(yvals[-1])+","
        string += "gt("+xStr+","+str(xvals[-1])+"))"
        
        return string
        #return "scipy.piecewise("+xStr+","+condlistStr+","+funclistStr+")[0]"
        
        
        
    # 7.27.2009
    def expectedAvgIntegratedErr(self,fittingData,indepParamsList=[[]]):
        """
        Return the expected average integrated error between the model
        producing the fittingData and the fittingModel with its
        current parameters.
        
        This number is related to the usual cost divided by the number of
        measurements, but 
        1) We have to remove the effect of different data 
        points having different uncertainty sigma;
        2) We don't want to include priors.
        """
        scm = self._SloppyCellDataModel(fittingData,indepParamsList,            \
            includePriors=False)
        residualValues = scipy.array( scm.res(self.getParameters()) )
        sigmas = scipy.array( [ r.ySigma for r in scm.residuals.values() ] )
        return scipy.average( (sigmas*residualValues)**2 )
    
class yeastOscillatorFittingModel(FittingModel):
    """
    For simulating the yeast oscillator using MATLAB.
    
    Doesn't implement fitting, etc.
    """
    def __init__(self,indepParamNames):
        """
        Independent parameters must be a subset of the following list:
            S1_init,S2_init,S3_init,S4_init,N2_init,A3_init,S4ex_init,temperature
        """
        self.indepParamNames = indepParamNames
        
        allVarNames = ['S1','S2','S3','S4','N2','A3','S4_ex',                   \
                       'ddt_S1','ddt_S2','ddt_S3','ddt_S4','ddt_N2'             \
                       'ddt_A3','ddt_S4_ex']
        self.varIndexDict = dict(zip(allVarNames,range(len(allVarNames))))
        self.varIndexDict['S4ex'] = self.varIndexDict['S4_ex'] # compatibility
        for v in allVarNames[:7]:
            self.varIndexDict[(v,'time')] = self.varIndexDict[v] + 7
        self.varIndexDict[('S4ex','time')] = self.varIndexDict[('S4_ex','time')]
        self.speciesNames = allVarNames
        
        allIndepParamNames = ['S1_init','S2_init','S3_init',                    \
                              'S4_init','N2_init','A3_init',                    \
                              'S4ex_init','temperature']
        indepParamIndexDict =                                                   \
            dict(zip(allIndepParamNames,range(len(allIndepParamNames))))
        # so I know which model parameter corresponds to each indepParam
        self.indepParamIndices =                                                \
            [ indepParamIndexDict[name] for name in self.indepParamNames ]
            
        # Table 2 of RuoChrWol03
        # units: mM (except for the last one, in K)
        self.defaultIndepParams =                                               \
                scipy.array([1.187,0.193,0.050,0.115,0.077,2.475,0.077,288.])
        
        self._savedEvalsFilename = 'yeast_savedEvalsDict.data'
        try:
            self.savedEvalsDict = load(self._savedEvalsFilename)
        except:
            self.savedEvalsDict = {}
    
    def typicalIndepParamRanges(self,upperRangeMultiple=1.):
        """
        Returns the typical ranges of initial conditions for the 
        parameters in self.indepParamNames.  Useful when creating
        random initial conditions, or when calling 
        FittingProblem.outOfSampleCorrelation.
        
        upperRangeMultiple (1.)     : Each typical range is expanded by this
                                      factor by increasing the upper limit.
        """
        includedIndices = self.indepParamIndices
        # taken from SchValJen11 Table 2
        ICranges = scipy.array(                                                 \
                   [[0.15,1.60],[0.19,2.16],                                    \
                    [0.04,0.20],[0.10,0.35],                                    \
                    [0.08,0.30],[0.14,2.67],[0.05,0.10]] )[includedIndices] # mM
        ICranges[:,1] = ICranges[:,0] +                                         \
            upperRangeMultiple*(ICranges[:,1]-ICranges[:,0])
        return ICranges
    
    def fitToData(self,fittingData,indepParamsList,verbose=verboseDefault):
        print "Oops!  fitToData needs to be implemented!"
        raise Exception
    
    def currentCost(self,fittingData,indepParamsList):
        print "Oops!  currentCost needs to be implemented!"
        raise Exception
    
    def currentHessian(self,fittingData,indepParamsList):
        print "Oops!  currentHessian needs to be implemented!"
        raise Exception
    
    def plotResults(self,fittingData,indepParamsList,numCols=None,              \
        plotSeparately=True,fmt=None,numPoints=500,minTime=0.,maxTime=None,     \
        dataToPlot=None,plotFittingData=False,linewidth=1.,numRows=None,        \
        newFigure=False,rowOffset=0,plotFirstN=None,linestyle=None,             \
        plotHiddenNodes=False,color=None):
        """
        numCols (None)      : 3.17.2013 set to 1 to plot all indepParams on a single
                              column.
        plotFirstN (None)   : 3.18.2013 if given an integer, plot first N
                              indepParams / fittingData combinations
                              (hack to avoid calling MATLAB)
        """
        if newFigure:
            Plotting.figure()
                
        if maxTime is None:
          allDataTimes = scipy.concatenate([ scipy.concatenate([                \
            varDat.keys() for varDat in data.values()])                         \
            for data in fittingData ])
          maxTime = 1.1 * max(allDataTimes)
        times = scipy.linspace(minTime,maxTime,numPoints)
        
        if plotFirstN is None:
            N = min(len(fittingData),len(indepParamsList))
        else:
            N = plotFirstN
        
        if not plotSeparately: # plot everything on one subplot
            raise Exception, "Error: plotSeparately=False not implemented"
        else:
            # assumes first dataset includes all species of interest
            varsWithData = fittingData[0].keys()
            
            if dataToPlot is None:
                # sort in the order they're found in self.speciesNames
                dataToPlotSorted = []
                for name in self.speciesNames:
                    #if plotDerivs: fullName = (name,'time')
                    #else: fullName = name
                    if name in varsWithData: dataToPlotSorted.append(name)
                    elif plotHiddenNodes: dataToPlotSorted.append(name)
            else:
                dataToPlotSorted = dataToPlot
            
            cW = Plotting.ColorWheel()
            if numCols is None:
                numCols = len(indepParamsList)
            if numRows is None:
                #numRows = scipy.ceil(float(len(dataToPlotSorted))/numCols)
                numRows = len(dataToPlotSorted)
            returnList = []
            for i,name in enumerate(dataToPlotSorted):
                axList = []
                ymins,ymaxs = [],[]
                # determine color and line format
                # (this may not be completely consistent)
                cWnext = cW.next()
                if linestyle is None: lineFmt = cWnext[2] 
                else: lineFmt = linestyle
                if fmt is None:
                    if name in varsWithData:
                        colorWheelFmt = cWnext
                    else: # 3.30.2012 plot hidden nodes gray by default
                        colorWheelFmt = 'gray','o',lineFmt
                else:
                    colorWheelFmt = fmt
                marker = colorWheelFmt[1]
                if color is None:
                    colorToUse = colorWheelFmt[0]
                else:
                    colorToUse = color
                j = -1
                for data,indepParams in zip(fittingData[:N],indepParamsList[:N]):
                  j += 1
                  #Plotting.subplot(numRows,numCols,i+1)
                  if numCols == 1:
                    subplotIndex = 1+(i+rowOffset)*numCols
                  else:
                    subplotIndex = j+1+(i+rowOffset)*numCols
                  ax = Plotting.subplot(numRows,numCols,subplotIndex)
                  if j==0: Plotting.ylabel(name)
                  axList.append(ax)
                  # remove middle axes labels
                  if j != 0: ax.get_yaxis().set_ticklabels([])
                  if i != len(dataToPlotSorted)-1: 
                      ax.get_xaxis().set_ticklabels([])
                  # plot continuous lines
                  modelTraj = self.evaluateVec(times,name,indepParams)
                  returnList.append( pylab.plot(times,modelTraj,ls=lineFmt,        \
                                                lw=linewidth,color=colorToUse) )
                  if plotFittingData and (name in varsWithData):
                      # plot data points
                      dataTimes = data[name].keys()
                      dataVals = [ data[name][time][0] for time in dataTimes ]
                      dataStds = [ data[name][time][1] for time in dataTimes ]
                      returnList.append( pylab.errorbar(dataTimes,dataVals,         \
                            yerr=dataStds,marker=marker,mfc=colorToUse,ls='',       \
                            ecolor='k') )
                
                  ranges = Plotting.axis()
                  ymins.append(ranges[2])
                  ymaxs.append(ranges[3])
                # make it pretty
                Plotting.subplots_adjust(wspace=0.,hspace=0.05)
                [ ax.axis(ymin=min(ymins),ymax=max(ymaxs)) for ax in axList ]
            
            return returnList
    
    def initializeParameters(self,paramList):
        print "Oops!  initializeParameters needs to be implemented!"
        raise Exception
    
    def evaluate(self,time,indepParams):
        print "Oops!  evaluate needs to be implemented!"
        raise Exception
    
    def evaluateVec(self,times,var,indepParams,useMemoization=True):
        """
        Currently only accepts equally-spaced times.
        
        var should be a single string or list of strings of variable names
        
        To get time derivative, use (var, 'time').
        
        Note to debuggers: 'Memoizes' results for faster performance.
        """
        if var in self.varIndexDict.keys(): # single var
            desiredVarIndices = self.varIndexDict[var]
        elif type(var) is not str: # iterable
            desiredVarIndices = [ self.varIndexDict[v] for v in var ]
        else:
            raise Exception, "Unknown variable "+str(var)
            
            
        params = self.defaultIndepParams
        params[self.indepParamIndices] = indepParams
        
        initialConditions = params[:7]
        temperature = params[7]
        
        key = (tuple(times),temperature,tuple(initialConditions))
        if self.savedEvalsDict.has_key(key) and useMemoization:
            returnedTimes,data,returnedParams = self.savedEvalsDict[key]
        else:
            returnedTimes,data,returnedParams =                             \
                simulateYeastOscillator(times,temperature,                  \
                                    initialConditions=initialConditions)
            self.savedEvalsDict[key] = returnedTimes,data,returnedParams
            try:
                save(self.savedEvalsDict,self._savedEvalsFilename)
            except:
                print "FittingProblem.YeastOscillatorFittingModel."         \
                    "evaluateVec: Unable to save memoization dictionary."
                #pass
               
        if len(times) != scipy.shape(data)[1]:
            print "FittingProblem.YeastOscillatorFittingModel.evaluateVec " \
                "WARNING: Returning different number of timepoints than "   \
                "requested."
            print "shape(times) =",scipy.shape(times)
            print "shape(data) =",scipy.shape(data)
                                                                              
        return data[desiredVarIndices]
            
        

    
class EnsembleGenerator():
    """
    Uses a simulated-annealing-type approach to search for
    the global minimum.  An initial ensemble is generated at
    temperature temp with totalSteps members, and keepSteps 
    of those (evenly spaced through the run) are used as 
    starting points for local Levenberg-Marquardt search.
    
    seeds           : A tuple of two integers to seed the
                    : random number generator.
    """
    def __init__(self,totalSteps,keepSteps,temperature=1.,sing_val_cutoff=0,    \
        seeds=None,logParams=False):
        
        self.totalSteps = totalSteps
        self.keepSteps = keepSteps
        self.temperature = temperature
        self.sing_val_cutoff = sing_val_cutoff
        self.seeds = seeds
        self.logParams = logParams
    
    def generateEnsemble(self,dataModel,initialParameters,returnCosts=False,    \
        scaleByDOF=True):
        """
        Also includes the initialParameters as the last set of parameters.
        """
        print "generateEnsemble: Generating parameter ensemble with "           \
            +str(self.totalSteps)+" total members."
        ensembleFunc = Ensembles.ensemble
        if self.logParams:
            ensembleFunc = Ensembles.ensemble_log_params
        
        # make sure our current parameters don't cause integration problems
        try:
            initialCost = dataModel.cost(initialParameters)
        except Utility.SloppyCellException:
            print "generateEnsemble: SloppyCellException in evaluating cost "   \
                  "for initial parameters.  Returning empty ensemble."
            initialCost = scipy.inf
            if returnCosts: return [[]],None,[None]
            else: return [[]],None
        try:
            if self.logParams:
                initialHess = dataModel.GetJandJtJInLogParameters(              \
                    scipy.log(initialParameters))[1]
            else:
                initialHess = dataModel.GetJandJtJ(initialParameters)[1]
            u, sing_vals, vh = scipy.linalg.svd(0.5 * initialHess)
        except Utility.SloppyCellException:
            print "generateEnsemble: SloppyCellException in evaluating JtJ "    \
                  "for initial parameters.  Returning empty ensemble."
            if returnCosts: return [[]],None,[None]
            else: return [[]],None
        
        # 4.5.2012 scale temperature by number of degrees of freedom
        # (to effectively divide chisq by dof)
        if scaleByDOF: dof = self._dataModelNumDataPoints(dataModel)
        else: dof = 1.
        ens,costs,ratio =                                                       \
            ensembleFunc(dataModel,initialParameters,                           \
                steps=self.totalSteps,seeds=self.seeds,                         \
                temperature=self.temperature*dof,                               \
                sing_val_cutoff=self.sing_val_cutoff,hess=initialHess)
        print "Ensemble done.  Acceptance ratio = "+str(ratio)
        skip = int( scipy.floor(self.totalSteps/(self.keepSteps-1)) )
        keptEns = scipy.concatenate( (ens[::-skip][:self.keepSteps-1],          \
            [initialParameters]) )
        keptCosts = scipy.concatenate( (costs[::-skip][:self.keepSteps-1],      \
            [initialCost]) )
        if returnCosts:
          return keptEns,ratio,keptCosts
        else:
          return keptEns,ratio
          
    def generateEnsemble_pypar(self,numprocs,dataModel,initialParameters,     \
          returnCosts=False,scaleByDOF=True):
          """
          Uses SloppyCell's built-in pypar support to run ensemble generation 
          (generateEnsemble) in parallel.
          """
          print "generateEnsemble_pypar: Generating parameter ensemble with "     \
            +str(self.totalSteps)+" total members, using "                        \
            +str(numprocs)+" processors."
            
          scipy.random.seed()
          prefix = "temporary_" + str(scipy.random.randint(1e8))                  \
              + "_generateEnsemble_pypar_"
          inputDictFilename = prefix + "inputDict.data"
          outputFilename = prefix + "output.data"
          inputDict = { 'ensGen':self,
              'dataModel':dataModel,
              'initialParameters':initialParameters,
              'returnCosts':returnCosts,
              'scaleByDOF':scaleByDOF,
              'outputFilename':outputFilename }
          save(inputDict,inputDictFilename)
          
          # call mpi
          stdoutFile = open(prefix+"stdout.txt",'w')
          call([ "mpirun","-np",str(numprocs),"python",                         \
                "generateEnsembleParallel.py",inputDictFilename ],              \
                stderr=stdoutFile,stdout=stdoutFile)
          stdoutFile.close()
          os.remove(inputDictFilename)
          
          try:
              output = load(outputFilename)
              os.remove(outputFilename)
              os.remove(prefix+"stdout.txt")
          except IOError:
              print "generateEnsemble_pypar error:"
              stdoutFile = open(prefix+"stdout.txt")
              stdout = stdoutFile.read()
              print stdout
              os.remove(prefix+"stdout.txt")
              raise Exception, "generateEnsemble_pypar:"                        \
                  + " error in generateEnsembleParallel.py"
          
          return output
    
    def _dataModelNumDataPoints(self,dataModel):
        return scipy.sum( [ [ [ len(varDat) for varDat in nameDat.values() ]    \
            for nameDat in exptDat.GetData().values() ]                         \
            for exptDat in dataModel.exptColl.values() ] )
    
            
class TranscriptionNetworkFittingModel(SloppyCellFittingModel):
    def __init__(self,outputName='output',                                      \
        indepParamNames=[],**kwargs):
        
        SloppyCellNet = TranscriptionNetwork.TranscriptionNetworkZiv()
        
        # generalSetup should be run by all daughter classes
        self.generalSetup(SloppyCellNet,indepParamNames,**kwargs)
        
class PowerLawFittingModel(SloppyCellFittingModel):
    """
    networkList  : list of the form
  
    [ [nodeType, { connectFrom: connectType, connectFrom: connectType, ...}], ... ]
        nodeType    : integer between 0 and 5 (the number of optimizable 
                      parameters specifying the node's behavior; 0 for input node)
        connectFrom : integer index of node to get connection from
        connectType : integer, either 1 or 2 (the number of parameters specifying
                      the connection)
                      
    indepParamNames     : list of names of independent parameters
    """
    
    def __init__(self,networkList,speciesNames=None,indepParamNames=[],             \
        includeRegularizer=True,logParams=True,useDeltaGamma=False,                 \
        maxSVDeig=1e5,minSVDeig=0.,**kwargs):
        """
        maxSVDeig (1e5)        : Maximum singular value allowed in svdInverse
        minSVDeig (0.)       : Minimum singular value allowed in svdInverse
        """
        
        n = len(networkList)
        
        if speciesNames is None:
            speciesNames = [ 'X_'+str(i) for i in range(n) ]
        self.speciesNames = speciesNames
        #speciesNames[0] = outputName
        #speciesNames[1:numInputs+1] = indepParamNames
        self.useDeltaGamma = useDeltaGamma
        self.includeRegularizer = includeRegularizer
        SloppyCellNet = PowerLawNetwork.PowerLaw_Network_List(                 \
            networkList,speciesNames,includeRegularizer=includeRegularizer,     \
            logParams=logParams,useDeltaGamma=useDeltaGamma)
            
        self.maxSVDeig,self.minSVDeig = maxSVDeig,minSVDeig
            
        #if initialParameters is not None:
        #    SloppyCellNet.setOptimizables(initialParameters)
            
        # generalSetup should be run by all daughter classes
        self.generalSetup(SloppyCellNet,indepParamNames,**kwargs)
    
    
    # 2.25.2013 taken from runFittingProblem.py
    def generateData_deriv(self,varsList,numConditions,noiseFracSize,           \
      indepParamsSeed=1,timeAndNoiseSeed=2,                                     \
      indepParamsRanges=None,timeRange=None,                                    \
      timepointsPerCondition=1,noiseInLog=True,T=1.):
      """
      Returns indepParamsList,fittingData,fittingDataDerivs.
      
      Varies all indepParams in self.indepParamNames, which may include
      initial conditions.  Since this function is for use in the derivative 
      problem, the returned indepParamsList does not include
      initial condition indepParams (those with names that end in '_init').
      
      indepParamsRanges (None)  : Range for each independent parameter in 
                                  fittingModel.  Defaults to 
                                  self.perfectModel.typicalIndepParamRanges()
                                  Shape (#indepParams)x(2)
      timeRange (None)      : Range of times at which to take data.  Defaults
                              to self.typicalTimeRange
      T (1.)                : "Temperature" parameter.  "Error bars" are
                              T times the size of the Gaussian noise added
                              to the perfect data.
      """
      #if indepParamNames is None:
      indepParamNames = self.indepParamNames
      nonICindepParamIndices =                                                  \
        filter( lambda i: not indepParamNames[i].endswith('_init'),             \
        range(len(indepParamNames)) )
      
      # () generate random independent parameters and times
      if indepParamsRanges is None:
        indepParamsRanges = self.typicalIndepParamRanges()
      if timeRange is None:
        timeRange = self.typicalTimeRange
      
      # generate random indepParams
      scipy.random.seed(indepParamsSeed)
      ipr = scipy.array(indepParamsRanges)
      randomIndepParams = scipy.rand(numConditions,len(indepParamsRanges))*     \
        (ipr[:,1]-ipr[:,0]) + ipr[:,0]
        
      # generate random times
      scipy.random.seed(timeAndNoiseSeed)
      tr = scipy.array(timeRange)
      randomTimes = scipy.rand(numConditions,timepointsPerCondition)*           \
        (tr[1]-tr[0]) + tr[0]
      
      # () calculate species values and derivatives 
      #    (taken from old correlationWithPerfectModel_deriv)
      fittingData,fittingDataDerivs = [],[]
      indepParamsList = []
      derivVarsList = [ (v,'time') for v in varsList ]

      # update "typical vals" for use with fractional error
      # use mean of typical indepParam ranges and typical time range
      # reset so SloppyCell doesn't give slightly different results
      typValsBefore = self.net.get_var_typical_vals()
      self.setInitialVariables( scipy.mean(self.typicalIndepParamRanges(),axis=1) )
      typVals = PerfectData.update_typical_vals([self.net],[self.typicalTimeRange])
      for v in typValsBefore.keys():
        self.net.set_var_typical_val(v,typValsBefore.get(v))

      # want same noise as we vary numConditions
      scipy.random.seed(int(timeAndNoiseSeed*1e6))
      # loop over conditions
      for times,indepParams in zip(randomTimes,randomIndepParams):
          # keep track of (non-IC) independent parameters for each condition
          if len(nonICindepParamIndices) > 0:
               indepParamsList.append(indepParams[nonICindepParamIndices])
          else:
               indepParamsList.append([])
      
          # d has shape (#species)x(#times)
          d = self.evaluateVec(times,varsList+derivVarsList,indepParams)
          data,dataDerivs = d[:len(varsList)],d[len(varsList):]
          
          # put data and deriv data into fittingData and fittingDataDerivs
          fittingDataI,fittingDataDerivsI = {},{}
          # loop over species
          for v,values,derivs in zip(varsList,data,dataDerivs):
              
              # 9.19.2012 Use noise on deriv prop. to maximal var value.
              # (Note: I'm not using the typical value of the derivative,
              #  but the typical value of the variable.)
              # (Note 2: I could imagine something more fancy that used
              #  the noise on values to get the size of noise on the
              #  derivatives, but I didn't do that.)
              if noiseFracSize > 0.:
                if noiseInLog:
                  valuesNoise = scipy.random.normal(0.,noiseFracSize,len(values))
                  derivsNoise = scipy.random.normal(0.,noiseFracSize,len(derivs))
                  valuesWithNoise = scipy.exp(valuesNoise) * values
                  derivsWithNoise = scipy.exp(derivsNoise) * derivs
                  valueSigmas = abs(values)*noiseFracSize # XXX 2.28.2013 other factors?
                  derivSigmas = abs(derivs)*noiseFracSize # XXX 2.28.2013 other factors?
                else:
                  typicalVarValue = typVals[v]
                  sigma = noiseFracSize*typicalVarValue
                  valuesWithNoise = abs(values + scipy.random.normal(0.,sigma,len(values)))
                  derivsWithNoise = derivs + scipy.random.normal(0.,sigma,len(derivs))
                  valueSigmas = sigma*scipy.ones_like(values)*T
                  derivSigmas = sigma*scipy.ones_like(derivs)*T
              else:
                  valuesWithNoise = values
                  derivsWithNoise = derivs
                  valueSigmas = scipy.zeros_like(values)
                  derivSigmas = scipy.zeros_like(derivs)
               
              fittingDataI[v] = dict( zip(times, zip(valuesWithNoise,           \
                                            valueSigmas) ) )
              fittingDataDerivsI[v] = dict( zip(times, zip(derivsWithNoise,     \
                                            derivSigmas) ) )
          fittingData.append(fittingDataI)
          fittingDataDerivs.append(fittingDataDerivsI)

        
      
      if False:
              # 2.26.2013 this is the way I was doing it in runFittingProblem.py
    
              # () generate species values
              fakeData = []
              for i,runVals in enumerate(runList):
                newNet = originalNet.copy()
                for runVar,runVal in zip(runVars,runVals):
                  newNet.setInitialVariableValue(runVar,runVal)
                fakeDataSingleRun = {}
                for var in outputVars:
                    # do individually so every var is 
                    # measured at the same (random) time
                    fakeDataSingleRun.update( FakeData.noisyFakeData(newNet,            \
                        numPoints,timeInterval,seed=int(timeAndNoiseSeed*1e5+i),        \
                        vars=[var],noiseFracSize=noiseFracSize,randomX=randomX,         \
                        includeEndpoints=includeEndpoints) )
                fakeData.append( fakeDataSingleRun )

              
              # () calculate derivatives (9.27.2012 back to numerically...)
              fittingDataDerivs = []
              scipy.random.seed(int(timeAndNoiseSeed*1e4+i))
              for runVals,conditionData in zip(runList,fakeData):
                conditionDerivs = {}
                for var in conditionData.keys():
                    varDerivs = {}
                    typicalVarValue = originalFittingModel.net.get_var_typical_val(var)
                    for time in conditionData[var].keys():
                        # do numerically
                        delta = 1e-5
                        val1,val2 = originalFittingModel.evaluateVec(                   \
                                                    [time-delta,time+delta],var,runVals)
                        deriv = (val2-val1)/(2.*delta)
                        
                        # do exactly (why doesn't this work? 9.27.2012)
                        #deriv = originalFittingModel.evaluate(time,(var,'time'),runVals)
                        
                        # 9.19.2012 Use noise on deriv prop. to typical var value.
                        # (Note: I'm not using the typical value of the derivative,
                        #  but the typical value of the variable.)
                        # (Note 2: I could imagine something more fancy that used
                        #  the noise on values to get the size of noise on the
                        #  derivatives, but I didn't do that.)
                        sigma = noiseFracSize*typicalVarValue
                        if sigma > 0.:
                            derivWithNoise = deriv + scipy.random.normal(0.,sigma)
                        else:
                            derivWithNoise = deriv
                        
                        varDerivs[time] = (derivWithNoise,sigma)
            
                    conditionDerivs[var] = varDerivs
                fittingDataDerivs.append(conditionDerivs)
    
      return indepParamsList,fittingData,fittingDataDerivs

    
    
    # 6.28.2012
    # 8.16.2012 to be checked: what happens when numInputs != 0
    def _derivProblem_getParams(self,numSpeciesTotal,numInputs,retTheta=False):
        """
        retTheta (False)        : Return thetaMatrixG and thetaMatrixH to be used
                                  with _derivProblem_regression
        """
        # 8.29.2012 changed to include hidden node parameters
        #Pg = scipy.zeros((numSpeciesTotal+1,numSpeciesNonHidden))
        #Ph = scipy.zeros((numSpeciesTotal+1,numSpeciesNonHidden))
        Pg = scipy.zeros((numSpeciesTotal+1+numInputs,numSpeciesTotal))
        Ph = scipy.zeros((numSpeciesTotal+1+numInputs,numSpeciesTotal))
        thetaG = scipy.ones_like(Pg)
        thetaH = scipy.ones_like(Ph)
        currentParams = self.getParameters()
        
        def getVal(name):
            if currentParams.has_key(name):
                if self.net.get_variable(name).is_optimizable:
                    return currentParams.get(name),1
                else:
                    return 0.,0
            else:
                return 0.,0
        
        for i in range(numInputs):
            for j in range(numSpeciesTotal):
                Pg[i,j],thetaG[i,j] = getVal('g_'+str(j+numInputs)+'_'+str(i))
                Ph[i,j],thetaH[i,j] = getVal('h_'+str(j+numInputs)+'_'+str(i))
        for i in range(numSpeciesTotal):
            if self.useDeltaGamma:
                Pg[numInputs,i],thetaG[numInputs,i] =                           \
                    getVal('log_delta_'+str(i+numInputs))
                hval = getVal('log_gamma_'+str(i+numInputs))[0] +               \
                    getVal('log_delta_'+str(i+numInputs))[0]
                htheta = getVal('log_gamma_'+str(i+numInputs))[1]
                Ph[numInputs,i],thetaH[numInputs,i] = hval,htheta
            else:
                Pg[numInputs,i],thetaG[numInputs,i] =                           \
                    getVal('log_alpha_'+str(i+numInputs))
                Ph[numInputs,i],thetaH[numInputs,i] =                           \
                    getVal('log_beta_'+str(i+numInputs))
            for j in range(numSpeciesTotal):
                Pg[i+1+numInputs,j],thetaG[i+1+numInputs,j] =                   \
                    getVal('g_'+str(j+numInputs)+'_'+str(i+numInputs))
                Ph[i+1+numInputs,j],thetaH[i+1+numInputs,j] =                   \
                    getVal('h_'+str(j+numInputs)+'_'+str(i+numInputs))
        if retTheta:
            return Pg,Ph,thetaG,thetaH
        else:
            return Pg,Ph
    
    # 3.4.2013
    def currentCost_deriv(self,fittingData,indepParamsList,fittingDataDerivs,   \
        includePriors=False,regStrength=0.):
        
        speciesData,speciesDataTimeDerivs,                                      \
            nonHiddenDataDerivs,nonHiddenDataDerivSigmas,indepParamsMat =       \
            self._derivProblem_createDataMatrices(fittingData,                  \
                                            fittingDataDerivs,indepParamsList)
        speciesDataTimeDerivSigmas = nonHiddenDataDerivSigmas
        
        numSpeciesTotal,numTimes = scipy.shape(speciesData)
        numIndepParams = len(indepParamsMat)
    
        Pg,Ph = self._derivProblem_getParams(numSpeciesTotal,numIndepParams)
        
        predictedDerivs = self._derivProblem_predictedDerivs(Pg,Ph,             \
            speciesData,indepParamsMat,regStrength)
        derivCost = scipy.sum(                                                  \
            ((speciesDataTimeDerivs - predictedDerivs)/speciesDataTimeDerivSigmas)**2 )
    
        return derivCost
    

    # 6.28.2012
    # 8.16.2012 to be checked: what happens when self.numInputs != 0
    # 8.29.2012 changed to include hidden node parameters
    def _derivProblem_setParams(self,Pg,Ph,numInputs):
        currentParams = self.getParameters()
        numSpeciesTotal = len(Pg)-1-numInputs
        #numSpeciesNonHidden = len(Pg[0])
        newParams = {}
        
        def setParam(name,val):
            if currentParams.has_key(name):
                newParams[name] = val
        
        for i in range(numInputs):
            for j in range(numSpeciesTotal):
                setParam('g_'+str(j+numInputs)+'_'+str(i), Pg[i,j])
                setParam('h_'+str(j+numInputs)+'_'+str(i), Ph[i,j])
        #for i in range(numInputs,numInputs+numSpeciesNonHidden):
        for i in range(numSpeciesTotal):
            if self.useDeltaGamma:
                setParam('log_delta_'+str(i+numInputs), Pg[numInputs,i])
                setParam('log_gamma_'+str(i+numInputs), Ph[numInputs,i]         \
                    - newParams['log_delta_'+str(i+numInputs)])
            else:
                setParam('log_alpha_'+str(i+numInputs), Pg[numInputs,i])
                setParam('log_beta_'+ str(i+numInputs), Ph[numInputs,i])
            for j in range(numSpeciesTotal):
                setParam('g_'+str(j+numInputs)+'_'+str(i+numInputs),            \
                    Pg[i+1+numInputs,j]) #Pg[j,i]
                setParam('h_'+str(j+numInputs)+'_'+str(i+numInputs),            \
                    Ph[i+1+numInputs,j]) #Ph[j,i]
        
        # sanity check that I'm not setting nonexistent parameters
        oldParameterNames = scipy.sort(currentParams.keys())
        newParameterNames = scipy.sort(newParams.keys())
        if scipy.shape(oldParameterNames) != scipy.shape(newParameterNames):
            raise Exception, "oldParameterNames != newParameterNames.\n"            \
                "old = "+str(oldParameterNames)+",\nnew = "+str(newParameterNames)
        if not scipy.all( oldParameterNames == newParameterNames ):
            raise Exception, "oldParameterNames != newParameterNames.\n"            \
                "old = "+str(oldParameterNames)+",\nnew = "+str(newParameterNames)
        
        self.net.setOptimizables(newParams)
    
    # shapes
    # Pg,Ph : (#indepParams + 1 + #species)x(#species)
    # G,H   : (#species)x(#data points)
    # speciesData, speciesDataTimeDerivs : (#species)x(#data points)
    # indepParamsMat : (#(nonIC?)indepParams)x(#times)
    #                = (#(nonIC?)indepParams)x(#conditions*timepts/condition)
    # indepParamsList : (#conditions)x(#indepParams)
    # D     : (#times)x(#indepParams + 1 + #species)
    
    
    
    # 6.28.2012
    # 8.30.2012 added indepParams
    def _derivProblem_productTerm(self,Pg,speciesData,indepParamsMat):
        """
        Calculates G given Pg and H given Ph.
        """
        numInputs = len(indepParamsMat)
        gIP = Pg[:numInputs,:] # gIP (#IPs)x(#species)
        logAlpha = Pg[numInputs,:] # logAlpha len #species
        g = Pg[numInputs+1:,:] # g (#species)x(#species)
        
        logIP = scipy.log(indepParamsMat) # logIP (#IPs)x(#times)
        logProdGIP = scipy.dot(gIP.T,logIP) # logProdGIP (#species)x(#times)
        
        logData = scipy.log(speciesData) # logData (#species)x(#times)
        logProdG = scipy.dot(g.T,logData) # logProdG (#species)x(#times) # g or g.T?
        
        logG = scipy.transpose([ logAlpha + lg + lgip for lgip,lg in            \
            zip(logProdGIP.T,logProdG.T) ])
        
        return scipy.exp(logG) # G (#species)x(#times)
        
    # 6.28.2012
    def _derivProblem_predictedDerivs(self,Pg,Ph,speciesData,indepParamsMat,r,  \
        separateTerms=False):
        G = self._derivProblem_productTerm(Pg,speciesData,indepParamsMat) * scipy.exp(r/speciesData)
        H = self._derivProblem_productTerm(Ph,speciesData,indepParamsMat) * scipy.exp(r*speciesData)
        predictedDerivs = G - H
        if separateTerms: return G,H
        else: return predictedDerivs
        
    # 6.27.2012
    # 7.19.2012 added weight matrix
    def _derivProblem_regression(self,Design,Y,includedIndices=None,weightMatrix=None,      \
        priorLambda=0.,thetaMatrix=None):
        """
        Returns parameter matrix Pg or Ph with shape (#indepParams + 1 + #species)x(#species)
        
        weightMatrix (None)     : A matrix the same shape as Y 
                                  (#species x #times) giving
                                  the weight of each residual in the
                                  regression.  Defaults to all ones.
        includedIndices (None)  : Give a list of time indices to only
                                  include those in the regression.
                                  (No longer actively supported.)
        priorLambda (0.)        : 2.27.2013 Strength of Gaussian prior
                                  on all parameters, centered on zero.
                                  P(p) = C exp( -priorLambda * p^2 )
        thetaMatrix (None)      : 3.3.2013 Matrix with same shape as Pg and Ph:
                                  (#indepParams + 1 + #species)x(#species).
                                  The element i,j is
                                     1 if j is influenced by parameter i
                                     0 if j is not influenced by i.
                                  Defaults to all ones (fully connected).
        """
        numSpecies,numTimes = scipy.shape(Y)
        numFactors = len(Design[0])
        if weightMatrix is None: weightMatrix = scipy.ones_like(Y)
        if includedIndices is None: includedIndices = range(numTimes)
        if thetaMatrix is None: thetaMatrix = scipy.ones((numFactors,numSpecies))
        W = scipy.transpose( (weightMatrix.T)[includedIndices] )
        D = Design[includedIndices]
        YT = scipy.real_if_close( (Y.T)[includedIndices] )
        YTTilde = W.T*W.T*YT
        P = []
        for i in range(numSpecies):
            # 8.30.2012 XXX check next line; was repeat(numSpecies+1,axis=0)
            #           (now need to add more rows to Wi for indepParams)
            Wi = scipy.array([W[i]]).repeat(len(D[0]),axis=0) # shape (#factors)x(#times)
            thetai = scipy.array([thetaMatrix[:,i]]).repeat(numTimes,axis=0) # (#times)x(#factors)
            DiTilde = Wi.T*thetai*D
            #Binv = scipy.linalg.inv(scipy.dot(DiTilde.T,DiTilde))
            priorTerm = priorLambda*scipy.diag(scipy.ones(len(D[0])))
            thetaTerm = scipy.diag(1-thetaMatrix[:,i]) # 3.3.2013 to keep B non-singular
            B = scipy.dot(DiTilde.T,DiTilde) + priorTerm + thetaTerm
            # ******************************************************
            #print "_derivProblem_regression: fitting species number",i
            #print "_derivProblem_regression: sum(Wi^2) =",scipy.sum(Wi**2)
            # ******************************************************
            try:
                Binv = svdInverse(B,maxEig=self.maxSVDeig,minEig=self.minSVDeig)
            except ZeroDivisionError:
                print "_derivProblem_regression: Singular matrix for species",i
                # 2.25.2013 not 100% sure this is the correct thing to do,
                # but it probably is if Wi is all zeros (which is what I'm
                # trying to fix).  I'll raise an exception in other cases to
                # be safe.
                if scipy.sum(Wi**2) != 0: raise Exception
                Binv = scipy.zeros( ( len(DiTilde[0]),len(DiTilde[0]) ) )
        
            # ***************
            if scipy.sum(scipy.imag(Binv)**2) > 0.:
                print "_derivProblem_regression: sum(imag(Binv)**2) =",scipy.sum(scipy.imag(Binv)**2)
            # ***************
            
            YiTilde = YTTilde[:,i]
            p2 = scipy.dot(thetai.T*D.T,YiTilde)
            Pi = scipy.dot(Binv,p2)
            P.append(Pi)
            # **********************************************************
            #print "_derivProblem_regression: fitting species number",i
            #print "_derivProblem_regression: param range =",(min(Pi),max(Pi))
            # **********************************************************
        return scipy.transpose(P)
        
        
    def _derivProblem_setOptimizable(self,visibleIndices,optBool,verbose=False):
        # fix parameters that will be fit using log-linear fit to derivatives
        allParamNames = self.net.get_var_vals().keys() #self.getParameters().keys()
        for paramName in allParamNames:
            paramNameSplit = paramName.rsplit('_')
            if len(paramNameSplit) > 1:
              # any g or h with first index in speciesIndicesWithData
              if (paramNameSplit[0] == 'g') or (paramNameSplit[0] == 'h'):
                if int(paramNameSplit[1]) in visibleIndices:
                    self.net.set_var_optimizable(paramName,optBool)
                    if verbose: print "fitToDataDerivs: setting optimizability of",paramName,"to",optBool
              # any log_gamma or log_delta with index in speciesIndicesWithData
              elif (paramNameSplit[1] == 'gamma') or (paramNameSplit[1] == 'delta'):
                if int(paramNameSplit[2]) in visibleIndices:
                    self.net.set_var_optimizable(paramName,optBool)
                    if verbose: print "fitToDataDerivs: setting optimizability of",paramName,"to",optBool
        
    # 8.22.2012
    def _derivProblem_setRandomParams(self,seed=0):
        # set random initial parameters (for now, uniform on (0,1)...)
        scipy.random.seed(seed)
        paramNames = self.getParameters().keys()
        randValues = scipy.rand(len(paramNames))
        self.initializeParameters(dict( zip(paramNames,randValues) ))
        
    # 12.14.2012
    def _derivProblem_createDataMatrices(self,fittingData,fittingDataDerivs,indepParamsList):
        """
        Transforms fittingData and fittingDataDerivs into matrices that can
        be used in log-linear fitting.
        
        Integrates at current paramters to find values of hidden species.
        
        Returns: speciesData,speciesDataTimeDerivs,                                 
            nonHiddenDataDerivs,nonHiddenDataDerivSigmas,indepParamsMat
            
        indepParamsMat does not include initial conditions.
        
        speciesData is of shape (# species)x(# data points)
        """
        if not ( (len(indepParamsList) == len(fittingData))                         \
             and (len(fittingData) == len(fittingDataDerivs)) ):
            raise Exception, "Lengths of fittingData, fittingDataDerivs, and "      \
                "indepParamsList are not equal."
        
        # copied from fitToDataDerivs
        speciesNamesWithData = filter(                                              \
            lambda name: name in fittingData[0].keys(),self.speciesNames)
        speciesIndicesWithData = [ self.speciesNames.index(name)                    \
            for name in speciesNamesWithData ]
        speciesNamesWithoutData = filter(                                           \
            lambda name: (name not in fittingData[0].keys())                        \
                    and (name not in self.indepParamNames),self.speciesNames)
        
        # 9.5.2012 separate the initial conditions from the other independent params
        indepParamICnames = filter(lambda name: name.endswith("_init"),             \
                                   self.indepParamNames)
        indepParamICindices = [ self.indepParamNames.index(name)                    \
                               for name in indepParamICnames ]
        if len(indepParamICindices) > 0:
            initialConditionsList = scipy.array(indepParamsList)[:,indepParamICindices]
        else:
            initialConditionsList = scipy.repeat([[]],len(indepParamsList),axis=0)
        # initialConditonsList (#conditions)x(#ICs)
        indepParamOtherNames = filter(lambda name: not name.endswith("_init"),      \
                                      self.indepParamNames)
        indepParamOtherIndices = [ self.indepParamNames.index(name)                 \
                                  for name in indepParamOtherNames ]
        if len(indepParamOtherIndices) > 0:
            indepParamsListOther = scipy.array(indepParamsList)[:,indepParamOtherIndices]
        else:
            indepParamsListOther = scipy.repeat([[]],len(indepParamsList),axis=0)
        # indepParamsListOther (#conditions)x(#indepParams)
        
        # ********************************************************
        #print "indepParamICnames = ",indepParamICnames
        #print "indepParamOtherNames = ",indepParamOtherNames
        #print "initialConditionsList = ",initialConditionsList
        #print "indepParamsListOther = ",indepParamsListOther
        # ********************************************************
        
        if False: # 3.4.2013 not sure why I was worried about this
        # 9.5.2012 test whether there are visible species without initial conditions
            visibleSpeciesWithoutICs = filter(lambda name:                              \
                        name+"_init" not in indepParamICnames, speciesNamesWithData)
            if len(visibleSpeciesWithoutICs) > 0:
                print "PowerLawFittingModel.fitToDataDerivs WARNING:"
                print "     These visible species have no ICs:",visibleSpeciesWithoutICs
        
        # set up the (constant) independent parameters matrix
        numIndepParams = len(indepParamsListOther[0])
        indepParamsMat = scipy.repeat([[]],numIndepParams,axis=0)
        if len(indepParamsListOther) != len(fittingData) : raise Exception
        for indepParamsOther,data in zip(indepParamsListOther,fittingData):
            numTimes = len(data.values()[0].keys())
            indepParamsRepeat = scipy.repeat([indepParamsOther],numTimes,axis=0).T
            indepParamsMat = scipy.concatenate([indepParamsMat,indepParamsRepeat],axis=1)
        #print "fitToDataDerivs: indepParamsMat =",indepParamsMat
        
        
        hiddenEmpty = scipy.repeat([[]],len(speciesNamesWithoutData),axis=0)
        nonHiddenEmpty = scipy.repeat([[]],len(speciesNamesWithData),axis=0)
        hiddenData,nonHiddenData = hiddenEmpty,nonHiddenEmpty
        hiddenDataDerivs,nonHiddenDataDerivs = hiddenEmpty,nonHiddenEmpty
        nonHiddenDataDerivSigmas = nonHiddenEmpty
        speciesDataTimeDerivs = []
        # () loop over conditions
        for indepParamsAll,data,derivData in                                        \
            zip(indepParamsList,fittingData,fittingDataDerivs):
                # find relevant times
                sortedTimes = scipy.sort(data.values()[0].keys())
                sortedDerivTimes = scipy.sort(derivData.values()[0].keys())
                if not scipy.all(scipy.equal(sortedTimes,sortedDerivTimes)):
                    raise Exception, "Data timepoints not the same as derivative timepoints"
                # () integrate to find values of hidden variables
                if len(speciesNamesWithoutData) > 0:
                    hiddenData = scipy.concatenate((hiddenData.T, self.evaluateVec(sortedTimes,speciesNamesWithoutData,indepParamsAll).T )).T
                    hiddenDataDerivs = scipy.concatenate((hiddenDataDerivs.T, self.evaluateVec(sortedTimes,[ (s,'time') for s in speciesNamesWithoutData ],indepParamsAll).T )).T
                # () extract values and derivatives of non-hidden variables
                nonHiddenDataOneIP,nonHiddenDataDerivsOneIP = [],[]
                nonHiddenDataDerivSigmasOneIP = []
                for name in speciesNamesWithData:
                    dataRow,dataRowDerivs,dataRowDerivSigmas = [],[],[]
                    for time in sortedTimes:
                        dataRow.append(data[name][time][0])
                        dataRowDerivs.append(derivData[name][time][0]) # [0] #9.19.12
                        dataRowDerivSigmas.append(derivData[name][time][1])
                    nonHiddenDataOneIP.append(dataRow)
                    nonHiddenDataDerivsOneIP.append(dataRowDerivs)
                    nonHiddenDataDerivSigmasOneIP.append(dataRowDerivSigmas)
                nonHiddenData = scipy.concatenate((nonHiddenData.T,scipy.transpose(nonHiddenDataOneIP))).T
                nonHiddenDataDerivs = scipy.concatenate((nonHiddenDataDerivs.T,scipy.transpose(nonHiddenDataDerivsOneIP))).T
                nonHiddenDataDerivSigmas = scipy.concatenate((nonHiddenDataDerivSigmas.T,scipy.transpose(nonHiddenDataDerivSigmasOneIP))).T
    
        if len(speciesNamesWithoutData) > 0:
            speciesData = scipy.concatenate((nonHiddenData,hiddenData))
            speciesDataTimeDerivs = scipy.concatenate((nonHiddenDataDerivs,hiddenDataDerivs)) # added hidden 8.17.2012
        else:
            speciesData = nonHiddenData
            speciesDataTimeDerivs = nonHiddenDataDerivs
        
        #print "shape(nonHiddenData) =",scipy.shape(nonHiddenData)
        #print "shape(nonHiddenDataDerivs) =",scipy.shape(nonHiddenDataDerivs)
        #print "shape(hiddenData) =",scipy.shape(hiddenData)
        #print "shape(hiddenDataDerivs) =",scipy.shape(hiddenDataDerivs)
        #print "shape(speciesData) =",scipy.shape(speciesData)
        #print "shape(speciesDataTimeDerivs) =",scipy.shape(speciesDataTimeDerivs)
        
        # throw ValueError if inf or nan shows up
        speciesData = scipy.asarray_chkfinite(speciesData)
        speciesDataTimeDerivs = scipy.asarray_chkfinite(speciesDataTimeDerivs)
        
        return speciesData,speciesDataTimeDerivs,                                   \
            nonHiddenDataDerivs,nonHiddenDataDerivSigmas,indepParamsMat
        
    # 12.14.2012
    def _derivProblem_calculateDerivs(self,fittingData,fittingDataDerivs,indepParamsList,r):
        """
        A faster way to evaluate derivatives when you don't need to integrate.
        
        (To fix: Shouldn't actually need fittingDataDerivs)
        """
        
        speciesData,speciesDataTimeDerivs,n,m,indepParamsMat =                      \
            self._derivProblem_createDataMatrices(fittingData,                      \
            fittingDataDerivs,indepParamsList)
        
        # taken from fitToDataDerivs (count only non-initial-condition indepParams)
        indepParamOtherNames = filter(lambda name: not name.endswith("_init"),      \
                                      self.indepParamNames)
        numIndepParams = len(indepParamOtherNames)
        
        numSpeciesTotal,numTimes = scipy.shape(speciesData)
        
        Pg,Ph = self._derivProblem_getParams(numSpeciesTotal,numIndepParams)
        predictedDerivs = self._derivProblem_predictedDerivs(Pg,Ph,speciesData,     \
            indepParamsMat,r)
            
        return predictedDerivs
        
    # 12.14.2012
    # 01.10.2013 changed to return list of correlations separated by variable
    def _derivProblem_outOfSampleCorrelation(self,outOfSampleFittingData,           \
        outOfSampleFittingDataDerivs,outOfSampleIndepParamsList,makePlot=False,     \
        regStrength=None,varList=None,newFigure=True):
        """
        Returns list of length (# variables).
        
        varList (None)              : List of variables to test.  Defaults
                                      to self.speciesNames.  For 
                                      "composite" variables, eg S2 = S2A*S2B,
                                      use the format [('S2A','S2B')].
        """
        
        if varList is None:
            varList = self.speciesNames
        
        varIndices = []
        for var in varList:
            if type(var) is tuple: # composite variable
                varIndex = [ self.speciesNames.index(v) for v in var ]
            else: # simple variable
                varIndex = self.speciesNames.index(var)
            varIndices.append(varIndex)
        
        if 'regStrength' in self.net.variables.keys():
            if regStrength is None:
                regStrength = self.net.get_var_val('regStrength')
        else:
            # if self.net doesn't have a regStrength parameter, it can't be nonzero
            if not ((regStrength == 0.) or (regStrength is None)): raise Exception
            regStrength = 0.
            
        
        flat = lambda a: scipy.reshape(a,scipy.prod(scipy.shape(a)))
        
        fittingData = outOfSampleFittingData
        fittingDataDerivs = outOfSampleFittingDataDerivs
        indepParamsList = outOfSampleIndepParamsList
    
        d,dd,actualDerivs,actualDerivsSigmas,m =                                    \
            self._derivProblem_createDataMatrices(fittingData,                      \
            fittingDataDerivs,indepParamsList)
        
        predictedDerivs = self._derivProblem_calculateDerivs(fittingData,           \
            fittingDataDerivs,indepParamsList,regStrength)
        
        corrs,pVals = [],[]
        for i,speciesName in zip(varIndices,varList):
            if type(i) is list: # composite variable
                actualSingleVar =                                                   \
                    scipy.prod([actualDerivs[index] for index in i],axis=0)
                predictedSingleVar =                                                \
                    scipy.prod([predictedDerivs[index] for index in i],axis=0)
            else: # simple variable
                actualSingleVar = actualDerivs[i]
                predictedSingleVar = predictedDerivs[i]

            if makePlot: # To do: make more fancy.  See plotDerivsResults
                if newFigure:
                    pylab.figure()
                pylab.plot(flat(actualSingleVar),flat(predictedSingleVar),'o')
                # plot diagonal
                low = min(min(flat(actualSingleVar)),min(flat(predictedSingleVar)))
                hi = max(max(flat(actualSingleVar)),max(flat(predictedSingleVar)))
                pylab.plot([low,hi],[low,hi],'k-')
                # make pretty
                pylab.axis([low,hi,low,hi])
                pylab.title(speciesName)
                pylab.xlabel('Actual time derivative')
                pylab.ylabel('Predicted time derivative')
            
            corr,pVal =                                                             \
                scipy.stats.pearsonr(flat(predictedSingleVar),flat(actualSingleVar))
            
            corrs.append(corr)
            pVals.append(pVal)
        
        return corrs,pVals
        
    # 8.15.2012
    def fitToDataDerivs(self,fittingData,fittingDataDerivs,indepParamsList=[[]],    \
                  otherStartingPoint=None,numLinearIter=100,maxiter=scipy.inf,      \
                  verbose=False,seed=None,retall=False,dataModel=None,              \
                  regStrength=0.,priorLambda=0.):
        """
        
        What happens with naming convention when there are inputs?  I think 
        the species nodes (non-input nodes) start at index #inputs.
        
        _derivProblem_fit assumes that the fittingData is associated with
        the nodes with indices starting at index #inputs.
        
        fittingData             : Should have data for all (non-hidden) species
                                  at every given timepoint.
        fittingDataDerivs       : In the same format (SloppyCell keyedList) 
                                  as fittingData, but listing time derivatives.
                                  Should be measured at the same times as
                                  in fittingData.
        indepParamsList ([[]])  : Should be the same length as fittingData and
                                  fittingDataDerivs, providing values for
                                  independent parameters in each condition.
                                  Initial conditions should be included here,
                                  too (corresponding to names in 
                                  self.indepParamNames that end in "_init");
                                  otherwise, default initial conditions will
                                  be used.
        dataModel (None)        : Optionally pass dataModel to save time
        regStrength (0.)        : See notes 1.30.2013.  Sets strength of 
                                  regularization.  regStrength=None sets
                                  regStrength to current
                                  regStrength parameter in self.net.
        priorLambda (0.)
                                  
        Note: As of 8.15.2012, does not take into account error bars on data.
        """
        
        if regStrength is None:
            regStrength = self.net.get_var_val('regStrength')
        
        speciesNamesWithData = filter(                                              \
            lambda name: name in fittingData[0].keys(),self.speciesNames)
        speciesIndicesWithData = [ self.speciesNames.index(name)                    \
            for name in speciesNamesWithData ]
        speciesNamesWithoutData = filter(                                           \
            lambda name: (name not in fittingData[0].keys())                        \
                     and (name not in self.indepParamNames),self.speciesNames)
                     
        noHiddenSpecies = ( len(speciesNamesWithoutData) == 0 )
        
        if seed is not None:
            # (this is now usually handled further upstream)
            # set random initial parameters (for now, uniform on (0,1)...)
            self._derivProblem_setRandomParams(seed)
        
        # 9.27.2012 set up SloppyCell dataModel to make cost evals easier
        # (could surely be done more efficiently)
        # 12.10.2012 disabled integration
        if (dataModel is None) and not noHiddenSpecies:
            dataModel = self._SloppyCellDataModel(fittingData,indepParamsList,              \
                fittingDataDerivs=fittingDataDerivs,includePriors=False,                    \
                disableIntegration=True)
        afterMinCostList,afterExpCostList = [],[]
        
        # run 
        i = 0
        paramsList = []
        oldCost = scipy.inf
        if dataModel is not None:
            newCost = dataModel.cost(self.getParameters())
        else:
            newCost = scipy.inf
        while (i < maxiter) and True: #newCost < oldCost: # XXX To do: better stop criterion
            
            i += 1
            if verbose:
                print ""
                print "fitToDataDerivs: Iteration",i
            
            if False:
                # (1) run nonlinear optimization for other parameters
                self._derivProblem_setOptimizable(speciesIndicesWithData,False,verbose)
                self.fitToData(fittingData,indepParamsList=indepParamsList,             \
                    otherStartingPoint=otherStartingPoint)
                self._derivProblem_setOptimizable(speciesIndicesWithData,True,verbose)
                
            try:
                # (2a) set up log-linear optimization using derivatives
                # (integrates to find hidden nodes)
                speciesData,speciesDataTimeDerivs,                                      \
                    nonHiddenDataDerivs,nonHiddenDataDerivSigmas,indepParamsMat =       \
                    self._derivProblem_createDataMatrices(fittingData,                  \
                    fittingDataDerivs,indepParamsList)
                
                # bad things can also happen within the log-linear fitting
                
                # (2b) run log-linear optimization using derivatives
                predictedDerivs = self._derivProblem_fit(speciesData,           \
                                       speciesDataTimeDerivs,                   \
                                       numiter=numLinearIter,verbose=verbose,   \
                                       indepParamsMat=indepParamsMat,           \
                                       regStrength=regStrength,                 \
                                       speciesDataTimeDerivSigmas=              \
                                            nonHiddenDataDerivSigmas,           \
                                       priorLambda=priorLambda)
                                       
                # 9.27.2012 calculate new cost before integrating hidden nodes
                predictedDerivsVisible = predictedDerivs[:len(nonHiddenDataDerivs)]
                afterMinCost = 0.5 * scipy.sum( ((predictedDerivsVisible-nonHiddenDataDerivs)/nonHiddenDataDerivSigmas)**2 )
                afterMinCostList.append( afterMinCost )
                afterMinCostNoSigma = scipy.sum( (predictedDerivsVisible-nonHiddenDataDerivs)**2 )
                                                  
                # (2c) 9.26.2012 calculate new cost after integrating hidden nodes
                oldCost = scipy.copy(newCost)
                if dataModel is not None:
                    try:
                        newCost = dataModel.cost(self.getParameters())
                    except Utility.SloppyCellException: 
                        #raise # for debugging
                        ## #(daeintException,ValueError,OverflowError):
                        print "fitToDataDerivs: Exception in cost evaluation. "
                        newCost = scipy.inf
                else:
                    newCost = afterMinCost
                    print "fitToDataDerivs: cost no sigma =",afterMinCostNoSigma
                print "fitToDataDerivs: cost =",newCost
                afterExpCostList.append(newCost)
                
            except (ValueError, OverflowError):
                # for debugging XX
                if False: raise
                
                # 8.30.2012 just return current parameters
                print "fitToDataDerivs: Exception in optimization. "            \
                      " Returning current parameters."
                if retall:
                    convFlag = 1
                    return self.getParameters(),afterMinCostList,afterExpCostList,convFlag
                else:
                    return self.getParameters()
                
                if verbose and False: # plot behavior
                    self.plotResults(fittingData,indepParamsList)
                    Plotting.title("Seed "+str(seed))
                
                # restart with new parameters
                seed += 1
                if verbose: print "fitToDataDerivs: *** ODEs produced "         \
                  "bad behavior.  Restarting with random seed",seed
                i = 0
                paramsList = []
                self._derivProblem_setRandomParams(seed)

                
            # 8.23.2012
            currentParams = self.getParameters()
            paramsList.append(currentParams)
          
        if i >= maxiter:
            print "fitToDataDerivs: Reached maxiter."
            bestParams = paramsList[-1]
            convFlag = 0
        else:
            print "fitTaDataDerivs: Cost increased at iteration "+str(i)
            if len(paramsList) > 1: bestParams = paramsList[-2]
            else: bestParams = paramsList[-1]
            convFlag = 2
            
        if retall:
            return bestParams,afterMinCostList,afterExpCostList,convFlag
        else:
            return bestParams
                
            
        
        
        
    # 6.27.2012
    def _derivProblem_fit(self,speciesData,speciesDataTimeDerivs,                   \
        numiter=10,setModelParams=True,maxReplaceValue=0,                           \
        verbose=True,maxfev=100,indepParamsMat=None,regStrength=None,               \
        speciesDataTimeDerivSigmas=None,priorLambda=0.):
        """
        Uses an alternating log-linear routine to fit the power law
        network given data on concentrations AND their time derivatives.
        
        speciesData             : Array with shape 
                                  (number of total species)x(number of times).
        speciesDataTimeDerivs   : Array with shape 
                                  (number of non-hidden species)x(number of times).
                                  The derivatives should be measured at the
                                  same times as the species concentrations.
        indepParamsMat (None)   : Optional array with shape
                                  (number of independent params)x(number of times).
        regStrength (None)      : See notes 1.30.2013.  Strength of regularization.
        speciesDataTimeDerivSigmas (None)   : Array with shape
                                  (number of total species)x(number of times).
                                  Defaults to all ones.
        priorLambda (0.)
        """
        if regStrength is None:
            regStrength = self.net.get_var_val('regStrength')
        r = regStrength
        
        if scipy.shape(speciesData) != scipy.shape(speciesDataTimeDerivs):
            raise Exception,                                                        \
                "speciesData must have same shape as speciesDataTimeDerivs"
        
        if indepParamsMat is None:
            numIndepParams = 0
        else:
            numIndepParams = len(indepParamsMat)
    
        if speciesDataTimeDerivSigmas is None:
            speciesDataTimeDerivSigmas = scipy.ones_like(speciesDataTimeDerivs)
        
        # (note that I now typically fit `hidden' derivatives in the
        #  EM framework, so numSpeciesNonHidden here is larger
        #  than the number of visible species in fitDataDerivs)
        numSpeciesTotal,numTimes = scipy.shape(speciesData)
        numSpeciesNonHidden,numTimes = scipy.shape(speciesDataTimeDerivs)
        
        # set up design matrix
        D = scipy.zeros((numTimes,numSpeciesTotal+1+numIndepParams))
        if numIndepParams > 0: 
            D[:,:numIndepParams] = scipy.transpose(indepParamsMat)
        D[:,numIndepParams] = scipy.ones(numTimes)
        D[:,numIndepParams+1:] = scipy.transpose(scipy.log(speciesData))
        
        # use model's current values for initial h parameters.
        # Pg and Ph store our parameters in a convenient form
        Pg,Ph,thetaMatrixG,thetaMatrixH =                                                   \
            self._derivProblem_getParams(numSpeciesTotal,numIndepParams,retTheta=True)
        if verbose:
            freeParams = int(scipy.sum(thetaMatrixG) + scipy.sum(thetaMatrixH))
            allParams = scipy.prod(scipy.shape(thetaMatrixG))                               \
                      + scipy.prod(scipy.shape(thetaMatrixH))
            print "_derivProblem_fit:",freeParams,"free parameters out of",allParams
        
        # 6.29.2012 for use in full nonlinear optimizer
        numParams = (numSpeciesTotal+1+numIndepParams)*numSpeciesTotal
        def residualFn(P):
            Pg = scipy.reshape(P[:numParams],(numSpeciesTotal+1+numIndepParams,numSpeciesTotal))
            Ph = scipy.reshape(P[-numParams:],(numSpeciesTotal+1+numIndepParams,numSpeciesTotal))
            predictedDerivs = self._derivProblem_predictedDerivs(Pg,Ph,speciesData,indepParamsMat,r)
            return scipy.reshape( speciesDataTimeDerivs - predictedDerivs,                  \
                                  scipy.prod(scipy.shape(predictedDerivs)) )

        
        #GnumIncludedIndicesList = []
        #HnumIncludedIndicesList = []
        derivCostList = []
        derivCostSubsetDeltaList = []
        deltaYhList = []
        deltaYgList = []
        
        # 2.25.2013
        def printParamSummary(Pg,Ph):
            if verbose:
                f = lambda mat: mat.reshape(scipy.prod(scipy.shape(mat)))
                print "_derivProblem_fit:  production params:",min(f(Pg)),"to",max(f(Pg))
                print "_derivProblem_fit: degradation params:",min(f(Ph)),"to",max(f(Ph))
        
        # 12.12.2012 commented this out
        #scipy.random.seed(1)
        #Pg = scipy.random.rand(*scipy.shape(Pg))
        #Ph = scipy.random.rand(*scipy.shape(Ph))
        
        # need to be set for first iteration
        includedIndices = []
        predictedDerivs = self._derivProblem_predictedDerivs(Pg,Ph,speciesData,indepParamsMat,r)
        oldPredYh = scipy.transpose(scipy.dot(D,Ph))
        G = self._derivProblem_productTerm(Pg,speciesData,indepParamsMat)
        Yh = scipy.log(G - speciesDataTimeDerivs)
        
        for i in range(numiter):
            
            # 6.29.2012 shuffle
            #if i%10 == 0:
            #    shuffle = scipy.random.shuffle
            #    shuffle(Pg)
            #    shuffle(Pg.T)
            #    shuffle(Ph)
            #    shuffle(Ph.T)
            
            if verbose: print "_derivProblem_fit: Iteration",i+1,"of",numiter
            
            # check whether new fit is better than old one,
            # at least at the included time indices
            predYh = scipy.transpose(scipy.dot(D,Ph))
            #oldDeltaYh = scipy.real_if_close( scipy.sum( (Yh-oldPredYh)[:,includedIndices]**2 ) )
            #newDeltaYh = scipy.real_if_close( scipy.sum( (Yh-predYh)[:,includedIndices]**2 ) )
            #deltaYhList.append(newDeltaYh)
            #if verbose: print "_derivProblem_fit: oldDeltaYh =",oldDeltaYh
            #if verbose: print "_derivProblem_fit: newDeltaYh =",newDeltaYh
            #oldDeltaExpYh = scipy.real_if_close( scipy.sum( (scipy.exp(Yh)-scipy.exp(oldPredYh))[:,includedIndices]**2 ) )
            #newDeltaExpYh = scipy.real_if_close( scipy.sum( (scipy.exp(Yh)-scipy.exp(predYh))[:,includedIndices]**2 ) )
            #if verbose:
            #    print "_derivProblem_fit: oldDeltaExpYh =",oldDeltaExpYh
            #    print "_derivProblem_fit: newDeltaExpYh =",newDeltaExpYh
            #    if oldDeltaYh < newDeltaYh: print "_derivProblem_fit: WARNING: fit getting worse: oldDeltaYh =",oldDeltaYh,", newDeltaYh =",newDeltaYh
            
            #derivCostSubset0 = scipy.sum( (speciesDataTimeDerivs - predictedDerivs)[:,includedIndices]**2 )
            predG,predH = self._derivProblem_predictedDerivs(Pg,Ph,speciesData,indepParamsMat,r,True)
            predictedDerivs = predG - predH
            
            #derivCostSubset1 = scipy.sum( (speciesDataTimeDerivs - predictedDerivs)[:,includedIndices]**2 )
            #derivCostSubsetDelta = derivCostSubset1 - derivCostSubset0
            #derivCostSubsetDeltaList.append(derivCostSubsetDelta)
            derivCost = scipy.sum( ((speciesDataTimeDerivs - predictedDerivs)/speciesDataTimeDerivSigmas)**2 )
            printParamSummary(Pg,Ph)
            if verbose: print "_derivProblem_fit: current deriv cost =", derivCost
            derivCostList.append(derivCost)
            
            oldPredYg = scipy.transpose(scipy.dot(D,Pg))
            
            # () Do fitting of production params while holding degradation fixed
            H = self._derivProblem_productTerm(Ph,speciesData,indepParamsMat)
            Yg = scipy.log(H + speciesDataTimeDerivs) - r/speciesData
            if True: # 7.19.2012 old included indices stuff (consider removing)
                #includedIndices = pylab.find( scipy.array([ scipy.all( h >= 0.) for h in scipy.transpose(H + speciesDataTimeDerivs) ]) )
                #if verbose: print len(includedIndices),"of",len(Yg.T)
                #GnumIncludedIndicesList.append(len(includedIndices))
                fittable = scipy.sum((H + speciesDataTimeDerivs)>0.)
                total = scipy.prod(scipy.shape(H))
                if verbose: print "_derivProblem_fit: production terms fit:",fittable,"of",total
            Wg = (H + speciesDataTimeDerivs) / speciesDataTimeDerivSigmas               \
                 * scipy.exp(-r/speciesData) * ((H + speciesDataTimeDerivs)>0.)
            Pg = self._derivProblem_regression(D,Yg,weightMatrix=Wg,                    \
                priorLambda=priorLambda,thetaMatrix=thetaMatrixG)
            
            # check whether new fit is better than old one,
            # at least at the included time indices
            predYg = scipy.transpose(scipy.dot(D,Pg))
            #oldDeltaYg = scipy.real_if_close( scipy.sum( (Yg-oldPredYg)[:,includedIndices]**2 ) )
            #newDeltaYg = scipy.real_if_close( scipy.sum( (Yg-predYg)[:,includedIndices]**2 ) )
            #deltaYgList.append(newDeltaYg)
            #if verbose:
            #    print "_derivProblem_fit: oldDeltaYg =",oldDeltaYg
            #    print "_derivProblem_fit: newDeltaYg =",newDeltaYg
            #    if oldDeltaYg < newDeltaYg: print "_derivProblem_fit: WARNING: fit getting worse: oldDeltaYg =",oldDeltaYg,", newDeltaYg =",newDeltaYg
            
            #derivCostSubset0 = scipy.sum( (speciesDataTimeDerivs - predictedDerivs)[:,includedIndices]**2 )
            predictedDerivs = self._derivProblem_predictedDerivs(Pg,Ph,speciesData,indepParamsMat,r)
            #derivCostSubset1 = scipy.sum( (speciesDataTimeDerivs - predictedDerivs)[:,includedIndices]**2 )
            #derivCostSubsetDelta = derivCostSubset1 - derivCostSubset0
            #derivCostSubsetDeltaList.append(derivCostSubsetDelta)
            derivCost = scipy.sum( ((speciesDataTimeDerivs - predictedDerivs)/speciesDataTimeDerivSigmas)**2 )
            printParamSummary(Pg,Ph)
            if verbose: print "_derivProblem_fit: current deriv cost =", derivCost
            derivCostList.append(derivCost)
            
            oldPredYh = scipy.transpose(scipy.dot(D,Ph))
            
            # () Do fitting of degradation params while holding production fixed
            G = self._derivProblem_productTerm(Pg,speciesData,indepParamsMat)
            Yh = scipy.log(G - speciesDataTimeDerivs) - r*speciesData
            if True: # 7.19.2012 old included indices stuff (consider removing)
                #includedIndices = pylab.find( scipy.array([ scipy.all( g >= 0.) for g in scipy.transpose(G - speciesDataTimeDerivs) ]) )
                #if verbose: print len(includedIndices),"of",len(Yh.T)
                #HnumIncludedIndicesList.append(len(includedIndices))
                fittable = scipy.sum((G - speciesDataTimeDerivs)>0.)
                total = scipy.prod(scipy.shape(G))
                if verbose: print "_derivProblem_fit: degradation terms fit:",fittable,"of",total
            Wh = (G - speciesDataTimeDerivs) / speciesDataTimeDerivSigmas               \
                 * scipy.exp(-r*speciesData) * ((G - speciesDataTimeDerivs)>0.)
            Ph = self._derivProblem_regression(D,Yh,weightMatrix=Wh,                    \
                priorLambda=priorLambda,thetaMatrix=thetaMatrixH)
        
            if False:
                # 6.29.2012 full nonlinear optimizer
                P0 = scipy.concatenate( (scipy.reshape(Pg,(numParams,)),                \
                                         scipy.reshape(Ph,(numParams,))) )
                P = scipy.optimize.leastsq(residualFn,P0,maxfev=maxfev)[0]
                Pg = scipy.reshape(P[:numParams],(numSpeciesTotal+1,numSpeciesNonHidden))
                Ph = scipy.reshape(P[-numParams:],(numSpeciesTotal+1,numSpeciesNonHidden))
                    
        if setModelParams:
            self._derivProblem_setParams(Pg,Ph,numIndepParams)
        
        #return Pg,Ph
        #return derivCostList,derivCostSubsetDeltaList,GnumIncludedIndicesList,HnumIncludedIndicesList,deltaYhList,deltaYgList
        
        predictedDerivs = self._derivProblem_predictedDerivs(Pg,Ph,speciesData,indepParamsMat,r)
        return predictedDerivs
      
        
class PowerLawFittingModel_Complexity(PowerLawFittingModel):
    """
    complexity      : integer specifying the "complexity" of the model
    """
    
    def __init__(self,complexity,indepParamNames=[],outputNames=[],**kwargs):
        
        # 2.22.2012 don't include indepParams ending in "_init" as inputs
        inputNames = filter(lambda name: name[-5:]!="_init",indepParamNames)
        
        self.complexity = complexity
        self.numInputs = len(inputNames)
        self.numOutputs = len(outputNames)
        
        # These numbers are specific to power-law networks.
        defaultOutputType = 3
        defaultType = 2
        maxType = 5
        maxConnection = 2
        self.networkList = _createNetworkList(complexity,self.numInputs,        \
            self.numOutputs,defaultType,defaultOutputType,maxType,maxConnection)
        self.n = len(self.networkList)
        
        speciesNames = [ 'X_'+str(i) for i in range(self.n) ]
        speciesNames[:self.numInputs] = inputNames
        speciesNames[self.numInputs:(self.numInputs+self.numOutputs)]           \
            = outputNames
        self.speciesNames = speciesNames
        
        PowerLawFittingModel.__init__(self,self.networkList,                    \
            speciesNames=speciesNames,indepParamNames=indepParamNames,**kwargs)
            
# 8.29.2012 
class PowerLawFittingModel_FullyConnected(PowerLawFittingModel_Complexity):
    """
    numSpecies          : integer specifying the total number of species 
                          (visible and hidden) in the model
    fracParams (1.)     : between 0. and 1. specifying the fraction of
                          parameters that are not fixed at 0
    indepParamNames     : names of independent parameters.  Any that end
                          in "_init" are treated as initial conditions.
    outputNames         : names of output (visible) species
    """
    
    def __init__(self,numSpecies,fracParams=1.,indepParamNames=[],              \
        outputNames=[],**kwargs):
        
        if len(outputNames) > numSpecies:
            raise Exception, "len(outputNames) > numSpecies"
        if (fracParams>1.) or (fracParams<0.):
            raise Exception, "fracParams must be between 0 and 1."
        
        # 2.22.2012 don't include indepParams ending in "_init" as inputs
        inputNames = filter(lambda name: not name.endswith("_init"),indepParamNames)
        
        numSpecies = numSpecies
        numInputs = len(inputNames)
        numOutputs = len(outputNames)
        numHidden = numSpecies - numOutputs
        
        # These numbers are specific to power-law networks.
        defaultOutputType = 3
        defaultType = 2
        maxType = 5
        maxConnection = 2
        # set complexity to that of a fully connected network
        fullComplexity = 2*numInputs*numHidden + 1*numInputs*numOutputs         \
            + (maxType-defaultOutputType)*numOutputs                            \
            + (maxType-defaultType)*numHidden                                   \
            + (maxConnection*(numSpecies - 1))*numSpecies
        # 3.4.2013
        complexity = int( fracParams*fullComplexity )
        print "PowerLawFittingModel_FullyConnected: complexity =",complexity
        
        PowerLawFittingModel_Complexity.__init__(self,complexity,               \
            indepParamNames=indepParamNames,outputNames=outputNames,**kwargs)
    
    # 2.14.2013
    # used in, eg, powerLawYeastOscillator
    def _setTerm(self,nameLHS,sign,factor,exponentList):
        """
        Example: nameLHS=S1, sign=-1, factor='k2', exponentList=[('S2A',2)]
        Sets degradation term of dS1/dt to k2*S2A**2.
        """
        net = self.net
        LHSi = str( self.speciesNames.index(nameLHS) )
        
        if sign == +1:
            # set factor
            f = factor
            #net.addAssignmentRule('delta_'+LHSi,f)
            net.addAssignmentRule('alpha_'+LHSi,f)
            expStr = 'g_'
        elif sign == -1:
            # set factor (a bit weird due to the definition of delta and gamma)
            #f = '('+factor+')/delta_'+LHSi
            f = factor
            net.addAssignmentRule('beta_'+LHSi,f)
            expStr = 'h_'
        else:
            raise Exception
        
        # set exponents
        for species,exponent in exponentList:
            # expand if needed
            if species in self.definitionDict.keys():
                nameList = self.definitionDict[species]
            else:
                nameList = [(species,1)]
            
            for nameRHS,expRHS in nameList:
                RHSi = str( self.speciesNames.index(nameRHS) )
                paramStr = expStr+LHSi+'_'+RHSi
                curExp = net.get_variable(paramStr).value
                net.set_var_val(paramStr,str(curExp)+'+'+str(expRHS)+'*'+str(exponent))

    # 2.22.2013
    def prune(self):
        """
        Remove factors with an exponent of zero from right-hand-sides.
        """
        net = self.net
        removedParameters = []
        for speciesLHS in net.species.keys():
          rhs = net.rateRules.get(speciesLHS)
          for i,speciesI in enumerate(self.speciesNames):
            for j,speciesJ in enumerate(self.speciesNames):
                gstr = 'g_'+str(i)+'_'+str(j)
                hstr = 'h_'+str(i)+'_'+str(j)
                if net.get_variable(gstr).value == 0.:
                    rhs = rhs.replace(speciesJ+'**'+gstr,'1.')
                    removedParameters.append(gstr)
                if net.get_variable(hstr).value == 0.:
                    rhs = rhs.replace(speciesJ+'**'+hstr,'1.')
                    removedParameters.append(hstr)
          net.addRateRule(speciesLHS,rhs)
        for param in scipy.unique(removedParameters):
            net.remove_component(param)

        
def _createNetworkList(complexity,numInputs,numOutputs,                         \
    defaultType,defaultOutputType,maxType,maxConnection):
        """
        Note: complexity != numParameters
        
        (Only works for 1 <= maxConnection <= 2)
        """
        
        #complexity,numInputs,numOutputs =                                       \
        #    self.complexity,self.numInputs,self.numOutputs
        
        networkList = []
        def done(curComplexity):
            if curComplexity[0] >= complexity:
                return True
            curComplexity[0] += 1
            return False
        curComplexity = [0]
        numHidden = 0
        
        def addConnection(node,connectedNode,connectionType):
            networkList[node][1][connectedNode] = connectionType
        
        # first add input and output nodes, with each output connected
        # to each input (this is complexity 0)
        for i in range(numInputs):
            networkList.append( [0, {}] )
        for i in range(numOutputs):
            networkList.append( [defaultOutputType,                             \
                dict( [ (i,1) for i in range(numInputs) ] )] )
        
        if done(curComplexity): return networkList
        
        # upgrade each input->output connection to 2
        if maxConnection is 2:
          for i in range(numOutputs):
            for j in range(numInputs):
                addConnection(numInputs+i,j,2)
                if done(curComplexity): return networkList
                
        # add connections among output nodes
        for connectionType in range(1,maxConnection+1):
          for i in range(numOutputs):
            for j in range(i+1,numOutputs):
              addConnection(numInputs+i,numInputs+j,connectionType) # was numInputs+i,j
              if done(curComplexity): return networkList
              addConnection(numInputs+j,numInputs+i,connectionType) # was j,numInputs+i
              if done(curComplexity): return networkList
              
        # upgrade each output node
        for nodeType in range(defaultOutputType+1,maxType+1):
          for i in range(numOutputs):
            networkList[numInputs+i][0] = nodeType
            if done(curComplexity): return networkList
           
        # add hidden nodes
        while True:
            # add node
            networkList.append( [defaultType, {}] )
            numHidden += 1
            curHidden = len(networkList)-1
            
            # add connections to, then from, output nodes
            for connectionType in range(1,maxConnection+1):
              for i in range(numOutputs):
                addConnection(numInputs+i,curHidden,connectionType)
                if done(curComplexity): return networkList
            for connectionType in range(1,maxConnection+1):
              for i in range(numOutputs):
                addConnection(curHidden,numInputs+i,connectionType)
                if done(curComplexity): return networkList
                
            # add connections from input nodes
            for connectionType in range(1,maxConnection+1):
              for i in range(numInputs):
                addConnection(curHidden,i,connectionType)
                if done(curComplexity): return networkList
                
            # add connections to and from all other nodes
            for connectionType in range(1,maxConnection+1):
              for i in range(numHidden-1):
                addConnection(numInputs+numOutputs+i,curHidden,connectionType)
                if done(curComplexity): return networkList
                addConnection(curHidden,numInputs+numOutputs+i,connectionType)
                if done(curComplexity): return networkList
            
            # upgrade type
            for nodeType in range(defaultType+1,maxType+1):
                networkList[curHidden][0] = nodeType
                if done(curComplexity): return networkList



def networkList2DOT(networkList,speciesNames,indepParamNames,               \
    filename,nodeShape='ellipse',indepParamColor='w',                       \
    speciesColors=None,Xcolor='gray',skipIndependentNodes=False,            \
    showWeights=False,**kwargs):
    """
    Uses pygraphviz to create a DOT file from the given networkList.
    
    prog ('neato')          :'neato','fdp',
    showWeights (False)     : True to label edges with weights
    
    (See also analyzeSparsenessProblem.drawNetworkFromMatrix 
     for more examples of pygraphviz usage.  See also
     http://www.graphviz.org/doc/info/attrs.html )
    """
    # 4.19.2011 from analyzeSparsenessProblem.py
    def RGBHdecimal2hex(RGBHdecimal):
        hexList = [ hex(int(256*x-1e-5))[2:] for x in RGBHdecimal ]
        hx = '#'
        for h in hexList:
            if len(h) == 1:
                hx = hx + '0' + h
            else:
                hx = hx + h
        return hx
        
    if speciesColors is None: speciesColors = Plotting.ColorWheel()
    
    # 2.22.2012 don't include indepParams ending in "_init" as inputs
    inputNames = filter(lambda name: name[-5:]!="_init",indepParamNames)
    
    # 2.22.2012 don't include indepParamNames in speciesNames
    speciesNamesFiltered =                                                  \
        filter(lambda name: name not in indepParamNames,speciesNames)

    G = AGraph(strict=False,**kwargs)
    allNames = inputNames + speciesNamesFiltered
    num = len(allNames)
    if num != len(networkList): 
        raise Exception, "total number of names ("+str(num)+") different "      \
            "than number of nodes in networkList ("+str(len(networkList))+")."
    allColors = list(scipy.repeat(indepParamColor,len(inputNames)))
    for i,color in zip(range(len(speciesNamesFiltered)),speciesColors):
        # in case it's from Plotting.ColorWheel
        if scipy.iterable(color): color = color[0] 
        allColors.append(color)
    nodeWidth,nodeHeight = 1,1
    ignoreIndices = []
    positionIndices = range(num)
    positionNum = num
    
    if skipIndependentNodes:
        positionNum = num - len(inputNames)
        #nodeIndices = nodeIndices[len(inputNames):]
        #allNames = allNames[len(inputNames):]
        #allColors = allColors[len(inputNames):]
        #networkList = networkList[len(inputNames):]
        ignoreIndices = range(len(inputNames))
        positionIndices = range(-len(inputNames),num-len(inputNames))
    
    twoPi = 2.*scipy.pi
    radius = 200.
    xList = [ str(radius*scipy.cos(twoPi*i/positionNum)) for i in positionIndices ]
    yList = [ str(radius*scipy.sin(twoPi*i/positionNum)) for i in positionIndices ] 
    
    # add nodes
    for i,name,color,x,y in zip(range(num),allNames,allColors,xList,yList):
    
      # color stuff
      if (name[:2] == "X_") and (Xcolor is not None):
        color = Xcolor
      RGBAcolor = matplotlib.colors.colorConverter.to_rgba(color)
      # change text color based on node color (from makeGroupsFigure)
      blackThresh = 1.2 #1.5
      if sum(RGBAcolor[:-1]) > blackThresh: fc = 'black'
      else: fc = 'white'
      hexColor = RGBHdecimal2hex(RGBAcolor)
      
      if i not in ignoreIndices:
        G.add_node(i,width=nodeWidth,height=nodeHeight,label=name,          \
          fillcolor=hexColor,style='filled',                                \
          shape=nodeShape,fontcolor=fc,pos=x+','+y)
    
    # add edges
    for i in range(num):
      if i not in ignoreIndices:
          for nodeIamAffectedBy in networkList[i][1].keys():
            
            if nodeIamAffectedBy not in ignoreIndices:
                weightList = networkList[i][1][nodeIamAffectedBy]
                if len(scipy.shape(weightList)) == 0: weightList = [weightList]
                weight = scipy.mean( weightList )
                if weight < 0.: arrowhead = 'odot'
                else: arrowhead = 'normal'
                minPenWidth = 0.3
                maxPenWidth = 10.
                if showWeights: 
                    label = ''.join([ '%1.2f '%w for w in weightList ])
                    penColor = 'gray52' #'slategray'
                else: 
                    label = ''
                    penColor = 'black'
                if abs(weight) < minPenWidth: 
                    style = 'solid' #'dotted'
                    penwidth = minPenWidth
                elif abs(weight) > maxPenWidth:
                    style = 'solid'
                    penwidth = maxPenWidth
                else: 
                    style = 'solid'
                    penwidth = abs(weight)
                G.add_edge(nodeIamAffectedBy,i,dir='forward',label=label,penwidth=penwidth,arrowhead=arrowhead,style=style,color=penColor)
    
    #G.draw(filename,prog=prog)
    
    if filename[-4:] != ".dot":
        filename = filename + ".dot"
    G.write(filename)
    #call(["neato","-n1","-o"+filename[:-4]+".png","-Tpng",filename])
    call(["neato","-n2","-o"+filename[:-4]+".png","-Tpng","-Gsplines=true",filename])
    return G
    
    
        
class LaguerreFittingModel(SloppyCellFittingModel):
    """
    Parameters can vary with a single input as arbitrary polynomials.
    
    polynomialDegreeList        : should be length degree+3
    """
    def __init__(self,degree,polynomialDegreeList=None,outputName='output',     \
        indepParamNames=[],**kwargs):
        
        SloppyCellNet = LaguerreNetwork.LaguerreNetwork(degree,outputName)
        priorSigma = None # assuming we won't want priors for Lauguerre fitting?
        
        if polynomialDegreeList is not None:
            # currently supports a single input
            inputName = indepParamNames[0]
            SloppyCellNet = VaryingParamsWrapper.VaryingParamsNet_Polynomial(   \
                SloppyCellNet,polynomialDegreeList,inputName )
        
        # generalSetup should be run by all daughter classes
        self.generalSetup(SloppyCellNet,indepParamNames,**kwargs)

# 7.20.2009
class PolynomialFittingModel(SloppyCellFittingModel):
    """
    Parameters can vary with a single input as arbitrary polynomials.
    
    polynomialDegreeList        : should be length degree+1
    
    Directly copied from PolynomialFittingModel.
    """
    def __init__(self,degree,polynomialDegreeList=None,outputName='output',     \
        indepParamNames=[],**kwargs):
        
        SloppyCellNet = PolynomialNetwork.PolynomialNetwork(degree,outputName)
        priorSigma = None # assuming we won't want priors for polynomial fitting?
        
        if polynomialDegreeList is not None:
            # currently supports a single input
            inputName = indepParamNames[0]
            SloppyCellNet = VaryingParamsWrapper.VaryingParamsNet_Polynomial(   \
                SloppyCellNet,polynomialDegreeList,inputName )
        
        # generalSetup should be run by all daughter classes
        self.generalSetup(SloppyCellNet,indepParamNames,**kwargs)


# 7.22.2009
class PhosphorylationFittingModel(SloppyCellFittingModel):
    """
    Parts copied from PolynomialFittingModel.
    """
    def __init__(self,n,rules=[],polynomialDegreeList=None,                     \
        outputName='totalPhos',                                                 \
        indepParamNames=[],MichaelisMenten=True,totalOffset=0.,                 \
        **kwargs):
        """
        The output measures the total phosphorylation.
        
        MichaelisMenten (True)  : if True, each reaction rate is modified to
                                  vary with the concentration of the substrate
                                  according to a simple Michaelis-Menten law.
        totalOffset (0.)        : Add an offset to the total phosphorylation
                                  (9.19.2012 trying this to help log-linear fitting)
        """
        self.n = n
        self.minimizeInLog = True
        
        # these shouldn't matter since we're using the SloppyCell implementation
        endTime,nSteps = 10,10
        
        phosModel = PhosphorylationFit_netModel.netModel(n,rules,endTime,nSteps,\
            MichaelisMenten=MichaelisMenten)
        params = scipy.ones( phosModel.numParams )
        SloppyCellNet = IO.from_SBML_file(phosModel.writeSBML(params))
        SloppyCellNet.set_id('PhosphorylationNet')
        
        # The output measures the total phosphorylation.
        sum = ''.join( [ 'Group_P'+str(i)+' + ' for i in range(1,n+1) ] )
        SloppyCellNet.addSpecies( outputName, SloppyCellNet.compartments.keys()[0] )
        SloppyCellNet.addAssignmentRule( outputName, str(totalOffset)+'+'+sum[:-3] )
        
        if polynomialDegreeList is not None:
            # currently supports a single input
            inputName = indepParamNames[0]
            SloppyCellNet = VaryingParamsWrapper.VaryingParamsNet_Polynomial(   \
                SloppyCellNet,polynomialDegreeList,inputName )
        
        # generalSetup should be run by all daughter classes
        self.generalSetup(SloppyCellNet,indepParamNames,**kwargs)

    

class CTSNFittingModel(SloppyCellFittingModel):
    """
    complexity      : integer specifying the "complexity" of the model
    
    Parts copied from PowerLawFittingModel, PowerLawFittingModel_Complexity
    """
    
    def __init__(self,complexity,indepParamNames=[],outputNames=[],                  \
        switchSigmoid=False,**kwargs):
        
        # 2.22.2012 don't include indepParams ending in "_init" as inputs
        inputNames = filter(lambda name: name[-5:]!="_init",indepParamNames)
        
        self.complexity = complexity
        self.numInputs = len(inputNames)
        self.numOutputs = len(outputNames)
        
        # These numbers are specific to CTSNs.
        defaultOutputType = 3
        defaultType = 1
        maxType = 4
        maxConnection = 1
        self.networkList = _createNetworkList(complexity,self.numInputs,        \
            self.numOutputs,defaultType,defaultOutputType,maxType,maxConnection)
        self.n = len(self.networkList)
        
        speciesNames = [ 'X_'+str(i) for i in range(self.n) ]
        speciesNames[:self.numInputs] = inputNames
        speciesNames[self.numInputs:(self.numInputs+self.numOutputs)]           \
            = outputNames
        self.speciesNames = speciesNames
        
        #n = self.n
        #numInputs = self.numInputs
        #if speciesNames is None:
        #    speciesNames = [ 'X_'+str(i) for i in range(n) ]
        #speciesNames[0] = outputName
        #speciesNames[1:numInputs+1] = indepParamNames
        
        #indepParamNames = inputNames
        
        self.switchSigmoid = switchSigmoid
        
        SloppyCellNet = CTSNNetwork.CTSN_List(self.networkList,self.speciesNames,      \
            switchSigmoid=switchSigmoid)
        
        #if initialParameters is not None:
        #    SloppyCellNet.setOptimizables(initialParameters)
            
        # generalSetup should be run by all daughter classes
        self.generalSetup(SloppyCellNet,indepParamNames,**kwargs)


class PlanetaryFittingModel(SloppyCellFittingModel):

    def __init__(self,indepParamNames=['r_init'],r_init=1,**kwargs):
        """
        Units of distance are rc = GM/(v0^2)
        Units of time are t0 = rc/v0 = GM/(v0^3)
        where G  = gravitational constant
        M  = mass of sun
        v0 = initial speed of object
        (assumed to be moving perpendicular
        to the line connecting it to the sun)
        """
        
        self.indepParamNames = indepParamNames
        self.speciesNames = ['r','theta']
        
        SloppyCellNet = PlanetaryNetwork.Planetary_net(r_init=r_init)
        
        # generalSetup should be run by all daughter classes
        self.generalSetup(SloppyCellNet,indepParamNames,**kwargs)



