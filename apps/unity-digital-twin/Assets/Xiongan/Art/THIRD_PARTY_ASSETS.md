# Visual asset provenance

## Pure-three-dimensional runtime boundary

The runtime contains no background photograph, road photograph, wall image,
facade atlas, PBR surface image, or HDRI.  Roads, curbs, walls, windows, roofs,
vegetation and sky are produced from real meshes, solid material parameters,
procedural geometry, Unity lights and the procedural sky shader.

Previously generated visual plates and downloaded surface images are retained
only under `outputs/3d/retired-image-assets` for audit history.  They are outside
Unity `Assets`/`Resources`, cannot enter the WebGL player, and are not used by
the runtime.

The retained third-party *mesh geometry* is released under CC0. Its image textures are not used by the runtime.

| Asset | Use | Source |
|---|---|---|
| Asphalt 03 | retired reference download; not packaged or rendered | https://polyhaven.com/a/asphalt_03 |
| Concrete Pavement 03 | retired reference download; not packaged or rendered | https://polyhaven.com/a/concrete_pavement_03 |
| Leafy Grass | retired reference download; not packaged or rendered | https://polyhaven.com/a/leafy_grass |
| Island Tree 02 | high-detail foreground street trees | https://polyhaven.com/a/island_tree_02 |
| Street Lamp 01 | high-detail foreground street lighting | https://polyhaven.com/a/street_lamp_01 |
| Kloofendal 48d Partly Cloudy Pure Sky | retired reference download; not packaged or rendered | https://polyhaven.com/a/kloofendal_48d_partly_cloudy_puresky |
| 3D Car by Lyricsz | SUMO passenger-vehicle mesh geometry | https://opengameart.org/content/3d-car-0 |
| Low Poly Car 3D by byzmod3d | alternate SUMO passenger-vehicle mesh geometry | https://opengameart.org/content/low-poly-car-3d |

License: https://polyhaven.com/license

Both vehicle assets are CC0. Their preview images and source archives remain in
`outputs/3d/third-party-downloads` for audit only. The player includes only FBX
mesh geometry, and Unity materials are assigned at runtime. No facade image
atlas or vehicle raster texture is used by the runtime.
