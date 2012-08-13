from .SRTM3 import sref, quads
from .SRTM3 import datasource as srtm3_datasource
from .VFP import datasource as vfp_datasource

def datasource(lat, lon, source_dir):
    '''
    '''
    vfp_ds = vfp_datasource(lat, lon, source_dir)
    
    if vfp_ds is not None:
        return vfp_ds
    
    return srtm3_datasource(lat, lon, source_dir)

def datasources(minlon, minlat, maxlon, maxlat, source_dir):
    """ Retrieve a list of VFP or SRTM3 datasources overlapping the tile coordinate.
    """
    lonlats = quads(minlon, minlat, maxlon, maxlat)
    sources = [datasource(lat, lon, source_dir) for (lon, lat) in lonlats]
    return [ds for ds in sources if ds]
