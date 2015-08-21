import json
from nupic.encoders import MultiEncoder
from regions.EEGSensor import EEGSensor
from nupic.engine import Network
from regions.SequenceClassifierRegion import SequenceClassifierRegion
from nupic.engine import pyRegions

_VERBOSITY = 0

SP_PARAMS = {
    "spVerbosity": _VERBOSITY,
    "spatialImp": "cpp",
    "globalInhibition": 1,
    "columnCount": 2048,
    "inputWidth": 0,
    "numActiveColumnsPerInhArea": 40,
    "seed": 1956,
    "potentialPct": 0.8,
    "synPermConnected": 0.1,
    "synPermActiveInc": 0.0001,
    "synPermInactiveDec": 0.0005,
    "maxBoost": 1.0,
}

TM_PARAMS = {
    "verbosity": _VERBOSITY,
    "columnCount": 2048,
    "cellsPerColumn": 32,
    "inputWidth": 2048,
    "seed": 1960,
    "temporalImp": "tm_py",
    "newSynapseCount": 20,
    "maxSynapsesPerSegment": 32,
    "maxSegmentsPerCell": 128,
    "initialPerm": 0.21,
    "permanenceInc": 0.1,
    "permanenceDec": 0.1,
    "globalDecay": 0.0,
    "maxAge": 0,
    "minThreshold": 9,
    "activationThreshold": 12,
    "outputType": "normal",
    "pamLength": 3,
}

SEQUENCE_CLASSIFIER_PARAMS = {"steps": "0",
                              "implementation": "py"}

PY_REGIONS = [r[1] for r in pyRegions]



def createEncoder(newEncoders):
  """
  Creates and returns a MultiEncoder.

  @param newEncoders    (dict)          Keys are the encoders' names, values are
      dicts of the params; an example is shown below.

  @return encoder       (MultiEncoder)  See nupic.encoders.multi.py.

  Example input:
    {"energy": {"fieldname": u"energy",
                "type": "ScalarEncoder",
                "name": u"consumption",
                "minval": 0.0,
                "maxval": 100.0,
                "w": 21,
                "n": 500},
     "timestamp": {"fieldname": u"timestamp",
                   "type": "DateEncoder",
                   "name": u"timestamp_timeOfDay",
                   "timeOfDay": (21, 9.5)},
    }
  """
  encoder = MultiEncoder()
  encoder.addMultipleEncoders(newEncoders)
  return encoder


def createSensorRegion(network, sensorType, encoders, dataSource):
  """
  Initializes the sensor region with an encoder and data source.

  @param network      (Network)

  @param sensorType   (str)           Specific type of region, e.g.
      "py.RecordSensor"; possible options can be found in /nupic/regions/.

  @param encoders     (dict, encoder) If adding multiple encoders, pass a dict
      as specified in createEncoder() docstring. Otherwise an encoder object is
      expected.

  @param dataSource   (RecordStream)  Sensor region reads data from here.

  @return             (Region)        Sensor region of the network.
  """
  # Sensor region may be non-standard, so add custom region class to the network
  if sensorType.split(".")[1] not in PY_REGIONS:
    # Add new region class to the network
    Network.registerRegion(EEGSensor)

  try:
    # Add region to network
    regionParams = json.dumps({"verbosity": _VERBOSITY})
    network.addRegion("sensor", sensorType, regionParams)
  except RuntimeError:
    print ("Custom region not added correctly. Possible issues are the spec is "
          "wrong or the region class is not in the Python path.")
    return

  # getSelf() returns the actual region, instead of a region wrapper
  sensorRegion = network.regions["sensor"].getSelf()

  # Specify how RecordSensor encodes input values
  if isinstance(encoders, dict):
    # Multiple encoders to add
    sensorRegion.encoder = createEncoder(encoders)
  else:
    sensorRegion.encoder = encoders

  # Specify the dataSource as a file RecordStream instance
  sensorRegion.dataSource = dataSource

  return sensorRegion


def createSpatialPoolerRegion(network, prevRegionWidth):
  """
  Create the spatial pooler region.

  @param network          (Network)   The region will be a node in this network.
  @param prevRegionWidth  (int)       Width of region below.
  @return                 (Region)    SP region of the network.
  """
  # Add region to network
  SP_PARAMS["inputWidth"] = prevRegionWidth
  spatialPoolerRegion = network.addRegion(
      "SP", "py.SPRegion", json.dumps(SP_PARAMS))

  # Make sure learning is ON
  spatialPoolerRegion.setParameter("learningMode", True)

  # Inference mode outputs the current inference (i.e. active columns).
  # Okay to always leave inference mode on; only there for some corner cases.
  spatialPoolerRegion.setParameter("inferenceMode", True)

  return spatialPoolerRegion


def createTemporalMemoryRegion(network, prevRegionWidth):
  """
  Create the temporal memory region.

  @param network          (Network)   The region will be a node in this network.

  @param prevRegionWidth  (int)       Width of region below.

  @return                 (Region)    TM region of the network.

  TODO: move the region widths validation to linkRegions()
  """
  # Make sure region widths fit
  if TM_PARAMS["columnCount"] != prevRegionWidth:
    raise ValueError("Region widths do not fit.")
  TM_PARAMS["inputWidth"] = TM_PARAMS["columnCount"]

  # Add region to network
  temporalMemoryRegion = network.addRegion(
      "TM", "py.TPRegion", json.dumps(TM_PARAMS))

  # Make sure learning is enabled (this is the default)
  temporalMemoryRegion.setParameter("learningMode", False)
  
  # We want to compute the predictedActiveCells
  # TODO: we can't use that output for now because the tm_py impl is broken
  # temporalMemoryRegion.setParameter("computePredictedActiveCellIndices", True)

  # Inference mode outputs the current inference (i.e. active cells).
  # Okay to always leave inference mode on; only there for some corner cases.
  temporalMemoryRegion.setParameter("inferenceMode", True)

  return temporalMemoryRegion


def createClassifierRegion(network, classifierType, prevRegionWidth):
  """
  Create classifier region.

  @param network          (Network)   The region will be a node in this network.
  @param classifierType   (str)           Specific type of region, e.g.
      "py.CLAClassifierRegion"; possible options can be found in /nupic/regions/.
  @param prevRegionWidth  (int)       Width of region below.
  @return                 (Region)    Classifier region of the network.

  """
  # Classifier region may be non-standard, so add custom region class to the network
  if classifierType.split(".")[1] not in PY_REGIONS:
    # Add new region class to the network
    network.registerRegion(SequenceClassifierRegion)
    PY_REGIONS.append(classifierType.split(".")[1])
  
  # Create the classifier region.
  classifierRegion = network.addRegion(
      "classifier", classifierType, json.dumps(SEQUENCE_CLASSIFIER_PARAMS))

  # Disable learning for now (will be enabled in a later training phase)... why???
  classifierRegion.setParameter("learningMode", False)

  # Inference mode outputs the current inference. We can always leave it on.
  classifierRegion.setParameter("inferenceMode", True)
  

  return classifierRegion


def createRegions(network, args):
  """
  Create the regions. @param args is to hold network params.
  Note the regions still need to be linked appropriately in linkRegions().

  @param new      (PyRegion)    If specified, this is a custom (new) region.
  """
  (dataSource,
   sensorType,
   classifierType,
   encoders) = args

  sensor = createSensorRegion(network, sensorType, encoders, dataSource)

  sp = createSpatialPoolerRegion(network, sensor.encoder.getWidth())

  tm = createTemporalMemoryRegion(network, sp.getSelf().columnCount)

  createClassifierRegion(network, classifierType, tm.getSelf().outputWidth)


def linkRegions(network):
  """Link the regions, as commented below."""
  # Link the SP region to the sensor input
  network.link("sensor", "SP", "UniformLink", "")

  # Forward the sensor region sequence reset to the SP
  network.link("sensor", "SP", "UniformLink", "",
      srcOutput="resetOut", destInput="resetIn")

  # Feed forward link from SP to TM
  network.link("SP", "TM", "UniformLink", "",
      srcOutput="bottomUpOut", destInput="bottomUpIn")

  # Feedback links (unnecessary??)
  network.link("TM", "SP", "UniformLink", "",
      srcOutput="topDownOut", destInput="topDownIn")
  network.link("TM", "sensor", "UniformLink", "",
      srcOutput="topDownOut", destInput="temporalTopDownIn")

  # Forward the sensor region sequence reset to the TM
  network.link("sensor", "TM", "UniformLink", "",
      srcOutput="resetOut", destInput="resetIn")

  # Feed the TM states to the classifier.
  network.link("TM", "classifier", "UniformLink", "",
      srcOutput = "bottomUpOut", destInput = "bottomUpIn")

  # Link the sensor to the classifier to send in category labels.
  # TODO: this link is useless right now because the classifier region
  # compute() function doesn't work... we are currently feeding TM states and
  # categories manually to the classifier via the customCompute() function.
  network.link("sensor", "classifier", "UniformLink", "",
      srcOutput = "categoryOut", destInput = "categoryIn")


def createNetwork(args):
  """
  Create the network instance with regions for the sensor, SP, TM, and
  classifier. Before running, be sure to init w/ network.initialize().

  @param args                   (dataSource, sensorType, encoders), more info:
    dataSource   (RecordStream) Sensor region reads data from here.
    sensorType   (str)          Specific type of region, e.g. "py.RecordSensor";
                                possible options can be found in nupic/regions/.
    classifierType   (str)      Specific type of classifier region, e.g. "py.CLAClassifier";
                                possible options can be found in nupic/regions/.
    encoders     (dict)         See createEncoder() docstring for format.

  @return        (Network)      sensor -> SP -> TM -> CLA classifier
  """
  network = Network()

  createRegions(network, args)

  linkRegions(network)

  return network

