from math import pi

from PIL import Image
import numpy

__all__ = 'data', 'tiles'

def arr2img(ar):
    """ Convert Numeric.array to PIL.Image.
    """
    return Image.fromstring('L', (ar.shape[1], ar.shape[0]), ar.astype('b').tostring())

def slope2bytes(slope):
    """ Convert slope from floating point to 8-bit.
    
        Slope given in radians, from 0 for sheer face to pi/2 for flat ground.
    """
    return (0xFF * numpy.sin(slope + pi/2)).astype(numpy.uint8)

def aspect2bytes(aspect):
    """ Convert aspect from floating point to 8-bit.
    
        Aspect given in radians, counterclockwise from -pi at north around to pi.
    """
    return (0xFF * (aspect/pi + 1)/2).astype(numpy.uint8)

def bytes2slope(bytes):
    """ Convert slope from 8-bit to floating point.
    
        Slope returned in radians, from 0 for sheer face to pi/2 for flat ground.
    """
    return pi/2 - numpy.arcsin(bytes.astype(numpy.float32) / 0xFF)

def bytes2aspect(bytes):
    """ Convert aspect from 8-bit to floating point.
    
        Aspect returned in radians, counterclockwise from -pi at north around to pi.
    """
    return (2 * bytes.astype(numpy.float32)/0xFF - 1) * pi
