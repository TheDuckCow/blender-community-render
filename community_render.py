# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 3
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

"""Community Render Add-on for taking user inputs and standardizing outputs.

Used to quickly and dynamically load multiple blend files, transform into a
standardized state, and help render them out to files.

The idea is the users (or 'authors') have submitted blend files through e.g. a
Google Form. Each blend file is loaded into a separately prepared template file
(template assigns render settings and lighting), some prep work done to
standardize the pulled in file, and then render it out to disk.

Some key factors for how this addon works:
- Blend files are assumed to have a single scene.
- This single scene is loaded in and instanced as an empty.
- The addon then "processes" the scene based on whatever is fit for the project
  (such as centering and selecting the intended object, clearing animations,
  and resizing to fit the render).
- Addon keeps tracks the overall render status of all entries.
"""

import csv
import os
import random
import time
from typing import Any, Dict, Optional, Sequence, Tuple

from bpy.app.handlers import persistent
import mathutils
import bpy


bl_info = {
    "name": "Community Render",
    "author": "Patrick W. Crawford",
    "version": (1, 5),
    "blender": (2, 90, 0),
    "location": "Properties > Scene > Community Render",
    "description": "Help load, transform, and render many blend files",
    "warning": "",
    "doc_url": "",
    "category": "Render",
}


CSV_META_PATH = "//csv_metadata.csv"
CSV_OUTPUT = "//csv_output.csv"

# Label of the the project, used in some places such as the panel
PROJECT_NAME = "Community Render"

# This is name of the collection in the master template to clear and load in
# scenes; this is NOT meant to be a collection name in each user's submitted
# files, there is no dependency on user-submitted naming convention.
LOCAL_COLLECTION_NAME = "load_scene"

# Text objects to update based on user loaded blend.
# Note: For maximum inclusive output, set up the source template with UTF8
# fonts to support special characters. Blender will not throw errors, but
# display boxes, if it cannot render certain characters.
AUTHOR_TEXT_OBJ = "author_text"
COUNTRY_TEXT_OBJ = "country_text"

# Image (next to render template) to use for any material has missing images.
REPLACEMENT_IMAGE = "default_texture.png"

# Enum value names for reuse
READY = "ready"
DONE = "done"
SKIP = "skip"
NOT_QUEUED = "not_queued"

# Used to temporarily save render samples before thumbnail render
PRIOR_RENDER = ()

# Stats used in UI, cached to avoid slow draws + enums
scene_stats = {}
NON_BLEND = "non_blend"
BLEND_COUNT = "blends"
RENDERED = "rendered"
NUM_QC_ERR = "num_qc_error"
NO_FORM_MATCH = "no_form_match"

# Flag to skip the finish render handler, after doing the thumbnail render.
_MID_RENDER = False
# Time in s that the current render started
_RENDER_START = 0
# Number of renders completed this session.
_RENDER_COUNT = 0


# -----------------------------------------------------------------------------
# General utilities
# -----------------------------------------------------------------------------


def generate_context_override(obj_list: Sequence[bpy.types.Object] = None
                              ) -> Dict[str, Any]:
    """Generate a custom override with custom object list."""
    if obj_list is None:
        obj_list = [ob for ob in bpy.context.view_layer.objects
                    if ob.select_get()]
    for window in bpy.context.window_manager.windows:
        screen = window.screen
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                override = {
                    'window': window,
                    'screen': screen,
                    'area': area,
                    'selected_objects': obj_list,
                }
                break
    return override


def make_annotations(cls) -> object:
    """Converts class fields to annotations if running with Blender 2.8"""
    if bpy.app.version < (2, 80):
        return cls
    bl_props = {k: v for k, v in cls.__dict__.items() if isinstance(v, tuple)}
    if bl_props:
        if '__annotations__' not in cls.__dict__:
            setattr(cls, '__annotations__', {})
        annotations = cls.__dict__['__annotations__']
        for k, v in bl_props.items():
            annotations[k] = v
            delattr(cls, k)
    return cls


def disable_auto_py(context) -> None:
    """Security measure to ensure auto-run python scripts is turned off."""
    prefs = context.preferences
    prefs.filepaths.use_scripts_auto_execute = False
    # Alt, less wide-reaching option: Add the current blends path to exclusion:
    # ind = len(prefs.autoexec_paths)
    # preferences.autoexec_path_add(index=...)


def format_seconds(seconds: float) -> str:
    """Take in seconds, return HH:MM:SS format."""
    hours = int(seconds // 3600)
    remain = seconds % 3600
    sec = int(remain % 60)
    minutes = int(remain // 60)
    return f"{hours:02d}:{minutes:02d}:{sec:02d}"


# -----------------------------------------------------------------------------
# Main process functions, used within operators
# -----------------------------------------------------------------------------


def get_responses_path(context) -> str:
    """Return the path for the expected TSV file."""
    default_name = "form_responses.tsv"
    props = context.scene.crp_props
    return bpy.path.abspath(os.path.join(props.config_folder, default_name))


def get_blend_file_list(context) -> Sequence[str]:
    abs_path = bpy.path.abspath(context.scene.crp_props.source_folder)
    dirname = os.path.dirname(abs_path)
    if not dirname:
        print("Target path is blank, no blends to load")
        return []
    if not os.path.isdir(dirname):
        print(f"Target folder does not exist: {dirname}")
        return []
    files = [blend for blend in os.listdir(dirname)
             if os.path.isfile(os.path.join(dirname, blend))
             and blend.lower().endswith(".blend")]

    count_all = len([blend for blend in os.listdir(dirname)
                     if os.path.isfile(os.path.join(dirname, blend))])

    # Update global stats
    scene_stats[NON_BLEND] = count_all - len(files)
    return sorted(files)


def load_active_row(context) -> None:
    """Load the active row's input."""
    load_active_selection(context)  # First, replace the loaded collection.
    process_open_file(context)  # Now run the process function
    update_scene_stats(context)  # QC may have updated

    # Reduce effect of memory leak over time, since we don't outright
    # delete references (since it was causing crashing/instability).
    # bpy.ops.outliner.orphans_purge()
    # Nope, this too can cause crashes. Plus it didn't save memory ultimately.


def load_active_selection(context) -> None:
    """Load the selection referenced in the UI list."""
    disable_auto_py(context)

    props = context.scene.crp_props
    blend = props.file_list[props.file_list_index].src_blend

    full_file = os.path.join(props.source_folder, blend)
    abs_path = bpy.path.abspath(full_file)

    if not os.path.isfile(abs_path):
        raise RuntimeError("Blend file not found: " + blend)
    print(f"Preparing to load: {blend}")

    prior_scenes = bpy.data.scenes[:]
    with bpy.data.libraries.load(abs_path, link=True) as (data_from, data_to):
        # Ensure only loading the first scene
        load_scn = data_from.scenes[0]
        data_to.scenes = [load_scn]
    current_scenes = bpy.data.scenes[:]
    new_scene_list = list(set(current_scenes) - set(prior_scenes))

    if not new_scene_list:
        raise Exception("Could not fetch loaded scene, maybe non loaded.")

    new_scene = new_scene_list[0]
    new_scene.name = blend

    # If scene was previously loaded, reset transform (doubles load time). This
    # ensures that "load original" will work even after loading with process
    # occurred once.
    # Note: While technically better behavior, this actually causes crashing.
    # if props.load_original:
    #     new_scene.library.reload()

    obj = replace_view_layer(context, new_scene)
    context.view_layer.objects.active = obj
    obj.select_set(True)
    row = props.file_list[props.file_list_index]
    obj.name = row.label

    update_use_text(None, context)

    print(f"Loaded {blend}:{new_scene.name} into object {obj.name}")


def remove_object(context, obj: bpy.types.Object) -> None:
    """Unlink an object from the scene, and remove from data."""
    print(f" > Removing object: {obj.name}")
    try:
        context.scene.collection.objects.unlink(obj)
    except RuntimeError:
        pass  # if not in master collection
    colls = list(obj.users_collection)
    for coll in colls:
        coll.objects.unlink(obj)
    obj.user_clear()

    # Common cause of crash, try periodic operator purge or file load instead.
    # bpy.data.objects.remove(obj)


def get_or_create_layercoll(context,
                            collection_name: str) -> bpy.types.LayerCollection:
    """Returns or creates the layer collection for a given name.

    Only searches within same viewlayer; not exact match but a non-case
    sensitive contains-text of collection_name check. If the collection exists
    elsewhere by name, ignore (could be used for something else) and generate
    a new one; maybe cause any existing collection to be renamed, but is still
    left unaffected in whatever view layer it exists.
    """
    master_vl = context.view_layer.layer_collection
    response_vl = None
    for child in master_vl.children:
        if collection_name.lower() not in child.name.lower():
            continue
        response_vl = child
        break
    if response_vl is None:
        new_coll = bpy.data.collections.new(collection_name)
        context.scene.collection.children.link(new_coll)
        # assumes added to scene's active view layer root via link above
        response_vl = master_vl.children[new_coll.name]
    return response_vl


def get_loaded_scene(context) -> Optional[bpy.types.Scene]:
    """Return the reference to the loaded scene if any."""
    view_layer = get_or_create_layercoll(context, LOCAL_COLLECTION_NAME)
    if not view_layer.collection.all_objects:
        return  # Nothing has been loaded yet.
    child = view_layer.collection.all_objects[0]
    if not (child.instance_type == 'COLLECTION' or child.instance_collection):
        print("Nothing loaded")
        raise Exception("Nothing loaded to remove")
    scene = [scn for scn in bpy.data.scenes
             if scn.collection == child.instance_collection]
    if len(scene) != 1:
        print("Expected single scene source")
        return None
    return scene[0]


def replace_view_layer(context, scene: bpy.types.Scene) -> bpy.types.Object:
    """Add and return an instance object of a given scene by reference."""
    view_layer = get_or_create_layercoll(context, LOCAL_COLLECTION_NAME)
    old_scene = get_loaded_scene(context)
    if old_scene is not None:
        bpy.data.scenes.remove(old_scene)

    this_empty = None
    for child in view_layer.collection.all_objects:
        if this_empty is None and child.type == 'EMPTY':
            this_empty = child
            continue
        remove_object(context, child)  # Should just be the empty with instance

    if this_empty is None:
        obj = bpy.data.objects.new(scene.name, None)
    else:
        obj = this_empty
    obj.instance_type = 'COLLECTION'
    obj.instance_collection = scene.collection

    if this_empty is None:
        # Link since we just added it
        view_layer.collection.objects.link(obj)
        obj.empty_display_type = 'CUBE'
        obj.empty_display_size = 0.1

    # instance.location = (0,0,0) # already the default
    return obj


def load_csv_metadata(context) -> Dict:
    """Load in the local C(T)SV metadata download of user form responses."""
    path = get_responses_path(context)
    if not os.path.isfile(path):
        print("TSV file not found!")
        return {}

    data = {}
    header = None
    with open(path, 'r', encoding='utf-8') as fd:
        rd = csv.reader(fd, delimiter="\t", quotechar='"')
        for row in rd:
            if not header:
                header = row
                if "blend_filename" not in header:
                    raise Exception("blend_filename not in CSV header")
                if "full_name" not in header or "country" not in header:
                    raise Exception("full_name/country not in CSV header")
                continue

            key = row[header.index("blend_filename")]
            user_name = row[header.index("full_name")]
            country = row[header.index("country")]

            # TODO: Check for profanity / other user-entered text issues.
            data[key] = {0: user_name, 1: country}
    return data


def process_open_file(context) -> None:
    """Transform the loaded scene into a standardized, desired format.

    Runs once directly after a blend file is loaded from the target folder,
    noting that the file is library linked in as a scene. This ensures nothing
    gets saved into the currently open file, and there is little concern for
    doing "cleanup" between opening different scenes (since data is not saved
    to the open file).

    The processing needed will vary for a given community project. Some sample
    utilities are included by default.
    """
    process_generic_scene(context)


def process_generic_scene(context) -> None:
    """Sample implementation of a scene transformation.

    This simple sample implementation performs a few useful tasks:
    - Clears all object-level animations, to ensure any object transforms
      can be simply performed
    - Remove / hide objects which are in an excluded collection view layer or
      hidden in the viewport or render in the source scene. A blender quirk is
      that a hidden or excluded collection in a scene will be visible if that
      scene is loaded as in instance into another scene (as this add-on does).
    - Scales and re-centers the scene around the visible meshes.
    """
    props = context.scene.crp_props
    this_row = props.file_list[props.file_list_index]

    # Get the current blend metadata, if needed for anything.
    # this_row = props.file_list[props.file_list_index]

    if props.load_original is True:
        print("Skip process step, not modifying loaded scene")
        return

    # delete all but allowed mesh types
    view_layer = get_or_create_layercoll(context, LOCAL_COLLECTION_NAME)
    coll = view_layer.collection
    if len(coll.all_objects) != 1:
        print("Expected only a single object in collection, found:")
        print(f"{len(coll.all_objects)} in {coll.name}")
        raise Exception("Issue - more than one object in collection!")

    scene = get_loaded_scene(context)

    # Now run any of the transformation steps. This are directly modifying the
    # scene as if objects were actually appended into the file, though indeed
    # it is actually library linked and so would reset on reload/open.
    clear_all_animation(scene)
    unlink_excluded_objects(scene)

    # Keep materials the same, just replace missing texture with a default.
    # update_materials(scene)

    # Completely clear and re-generate any materials missing images.
    # regenerate_missing_materials(scene)

    # Find the largest object in the scene which is a mesh, and has enough
    # geometry that it's not likely a backdrop or floor.
    avg_pos = None
    xy_scale = None
    target_obj = None
    for obj in scene.collection.all_objects:
        if obj.type != 'MESH':
            continue
        if len(obj.data.polygons) < 100:  # Likely a plane or backdrop.
            continue
        this_pos, this_scale = get_avg_pos_and_scale(context, obj)
        if target_obj is None or this_scale > xy_scale:
            avg_pos = this_pos
            xy_scale = this_scale
            target_obj = obj

    if target_obj is None:
        this_row.qc_error = "Could not select target object"
        print("No objects remain")
        return
    else:
        print(f"Selected target object {target_obj.name}")

    # Assign the center for the scene to use by adjusting the instance offset.
    scene.collection.instance_offset = this_pos

    # Update the scale of the scene instance (not changing scale in source).
    target_width = 1.0  # Meters.
    if xy_scale > 0.000001:
        transform_scale = target_width / xy_scale
    else:
        transform_scale = 1
    print(f"XY scale is: {xy_scale} and pos avg {avg_pos}")
    empty_inst = context.view_layer.objects.active
    empty_inst.scale = [transform_scale] * 3


def clear_all_animation(scene: bpy.types.Scene) -> None:
    """Remove all animation from the open scene."""
    for ob in scene.collection.all_objects:
        ob.animation_data_clear()


def unlink_excluded_objects(scene: bpy.types.Scene) -> None:
    """Actively unlink objects that are excluded in the source scene.

    Will also attempt to remove archived or default hidden collections
    """
    master = scene.view_layers[0].layer_collection
    for child in master.children:
        excluded = child.exclude is True
        # archive = "archive" not in child.name.lower()
        hidden = child.collection.hide_viewport or child.collection.hide_render
        hidden = hidden or child.hide_viewport  # Like hide_get() for objects.

        # If collection is archive, always exclude it.
        if not (excluded or hidden):
            continue
        # Just unlink this view layer. Deleting objects would likely mean
        # that the sprinkles would get deleted too.
        print(f"\tUnlinked excluded layer: {child.collection.name}")
        master.collection.children.unlink(child.collection)


def get_avg_pos_and_scale(
        context, obj: bpy.types.Object) -> Tuple[mathutils.Vector, float]:
    """Return the average position and scale for the give object.

    Returns:
        average position: XYZ position based on bounding box, not origin.
        scale: Width of object (average of xy individually).
    """
    sum_pos = mathutils.Vector([0, 0, 0])
    min_x = None
    max_x = None
    min_y = None
    max_y = None
    min_z = None
    max_z = None

    # Counteract rotation so that bounding box isn't enlarged unnecessarily.
    # Note: Below is not fully correct, and for sake of simplicity, opted to
    # rotate and then un-rotate the selected object instead.
    # zrot = obj.rotation_euler[2]
    # counter_rot = mathutils.Matrix.Rotation((zrot), 4, 'Z')

    bounds = [obj.matrix_world @ mathutils.Vector(corner)  # @ counter_rot
              for corner in obj.bound_box]
    for bound in bounds:
        sum_pos += bound
        if not min_x or bound[0] < min_x:
            min_x = bound[0]
        if not max_x or bound[0] > max_x:
            max_x = bound[0]
        if not min_y or bound[1] < min_y:
            min_y = bound[1]
        if not max_y or bound[1] > max_y:
            max_y = bound[1]
        if not min_z or bound[2] < min_z:
            min_z = bound[2]
        if not max_z or bound[2] > max_z:
            max_z = bound[2]

    current_size = mathutils.Vector([
        max_x - min_x,
        max_y - min_y,
        max_z - min_z])

    avg_pos = sum_pos / 8  # Div by 8 for the number of bound box corners.
    xy_scale = (current_size[0] + current_size[1]) / 2.0

    return avg_pos, xy_scale


def update_materials(scn: bpy.types.Scene) -> None:
    """Replace missing image links in scene with the default image."""
    default = None
    default_path = bpy.path.abspath("//" + REPLACEMENT_IMAGE)
    if not os.path.isfile(default_path):
        raise Exception(f"Default texture is missing: {default_path}")
    for img in bpy.data.images:
        if img.filepath and bpy.path.abspath(img.filepath) == default_path:
            default = img
            break

    if default is None:
        default = bpy.data.images.load(default_path)

    mat_list = materials_from_obj(scn.collection.all_objects)
    eevee_src = scn.render.engine == 'BLENDER_EEVEE'
    for mat in mat_list:
        # Use the default texture
        replace_missing_textures(mat, default)

        # Not working yet as intended
        # if eevee_src:
        #     disable_displacement(mat)


def regenerate_missing_materials(scn: bpy.types.Scene) -> None:
    """Iterate through all objects in the scene, update materials as needed."""
    mat_list = materials_from_obj(scn.collection.all_objects)
    for mat in mat_list:
        if detect_missing_images_in_material(mat):
            print(f"Updating material with missing images: {mat.name}")
            replace_material_nodes(mat)


def materials_from_obj(
        obj_list: Sequence[bpy.types.Object]) -> Sequence[bpy.types.Material]:
    """Get a de-duplicated list of materials across the input objects."""
    mat_list = []
    for obj in obj_list:
        # Also capture obj materials from dupliverts/instances on e.g. empties.
        if hasattr(obj, "instance_collection") and obj.instance_collection:
            for dup_obj in obj.instance_collection.objects:
                if dup_obj not in obj_list:
                    obj_list.append(dup_obj)  # Will iterate over this at end.
        if not hasattr(obj, "material_slots") or not obj.material_slots:
            continue
        for slot in obj.material_slots:
            if slot.material is not None and slot.material not in mat_list:
                mat_list.append(slot.material)
    return mat_list


def detect_missing_images_in_material(material: bpy.types.Material) -> bool:
    """Return true if any missing (non packed) image in the material."""
    if not material.use_nodes:
        return False
    for node in material.node_tree.nodes:
        if node.type != "TEX_IMAGE":
            continue
        if not node.image:
            # Should this count as a fail?
            continue
        # Now check if the image contains any data, but in an efficient manner.
        if node.image.packed_file:
            # TODO: check if pixel data loaded, though if packed likely ok.
            continue
        else:
            return True


def replace_missing_textures(
        material: bpy.types.Material, replacement: bpy.types.Image) -> None:
    """Find and replace any missing images on the target material."""
    if not material.use_nodes:
        return False
    for node in material.node_tree.nodes:
        if node.type != "TEX_IMAGE":
            continue
        if not node.image:
            node.image = replacement
            continue
        if node.image.packed_file:
            # TODO: check if pixel data loaded, though if packed likely ok.
            continue
        # Could check node.image.filepath, but really if it's not packed,
        # there's likely no chance of it being a valid reference.
        node.image = replacement


def replace_material_nodes(material: bpy.types.Material) -> None:
    """Replace the given material nodes with hard coded expected ones."""
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    nodes.clear()
    new_diffuse = nodes.new(type="ShaderNodeBsdfDiffuse")
    output = nodes.new(type="ShaderNodeOutputMaterial")
    links.new(new_diffuse.outputs[0], output.inputs[0])

    browncol = (0.202386, 0.0970994, 0.0155558, 1)
    new_diffuse.inputs['Color'].default_value = browncol


def regenerate_materials(
        target: bpy.types.Material, reference: bpy.types.Material) -> None:
    """Regenerate a given material to match (closely) a given target's.

    Can't just copy or replace the material on linked in scenes, so instead we
    reconstruct it.

    Args:
        target: The material to be cleared and recreated, on a linked object.
        reference: The reference material to pull node layout from
    """
    target.node_tree.nodes.clear()
    tnodes = target.node_tree.nodes
    tnodes.clear()
    tlinks = target.node_tree.links

    node_lookup = {}
    for node in reference.node_tree.nodes:
        new_node = tnodes.new()
        node_lookup[node] = new_node

        # Try to match all properties possible too.
        print("TODO: update material properties")

    for link in reference.node_tree.links:
        tlinks.new(
            node_lookup[link.from_node],
            link.from_socket,
            node_lookup[link.to_node],
            link.from_socket
        )


def disable_displacement(material: bpy.types.Material) -> None:
    """For use in e.g. eevee scenes where displacement has no effect.

    Needed for scenes where Eevee is active in source, but rendering is done
    in cycles, and thus unexpected displacement appears and messes up renders.
    """
    if not material.use_nodes:
        return
    nodes = material.node_tree.nodes
    outputs = [node for node in nodes if node.type == "OUTPUT_MATERIAL"]
    del_links = []
    for out in outputs:
        cur_links = list(out.inputs[-1].links)
        del_links += cur_links
    for link in del_links:
        material.node_tree.links.remove(link)

# -----------------------------------------------------------------------------
# Render functions and controllers
# -----------------------------------------------------------------------------


def render_open_file(context) -> None:
    """Render the current open file, with both high res and low res."""
    props = context.scene.crp_props
    for row in props.file_list:
        row.queue_status = SKIP
    this_row = props.file_list[props.file_list_index]
    this_row.queue_status = READY
    initiate_render_queue(context)


def queue_all_files(context) -> None:
    """Loop over all in scope files and prepare them for rendering."""
    props = context.scene.crp_props
    for row in props.file_list:
        if row.qc_error != "" or row.render_exists:
            row.queue_status = SKIP
        else:
            row.queue_status = READY


def render_timer_callback() -> float:
    """Callback used within model of interactive rendering.

    Returns:
        Float: None if render done, or 0 to call to re-register the timer.
    """
    props = bpy.context.scene.crp_props
    if not props.render_running:
        return None

    this_render = None
    for row in props.file_list:
        if row.queue_status == READY:
            this_render = row
            break

    if this_render is None:
        if PRIOR_RENDER:
            bpy.context.scene.render.resolution_x = PRIOR_RENDER[0]
            bpy.context.scene.render.resolution_y = PRIOR_RENDER[1]
        props.render_running = False
        return None  # Will not re-register this timer callback

    # If render_running is True, will do callback automatically of
    # single_render_complete(bpy.context)
    render_next_in_queue(bpy.context, interactive=False)
    global _RENDER_COUNT
    _RENDER_COUNT += 1

    return 0.0  # Will re-register this timer callback, with s delay.


def initiate_render_queue(context) -> None:
    """Start the render queue."""
    props = context.scene.crp_props
    remaining_renders = [row for row in props.file_list
                         if row.queue_status == READY]
    if not remaining_renders:
        print("Nothing to render in queue")
        props.render_running = False
        # Always revert samples back
        if PRIOR_RENDER:
            context.scene.render.resolution_x = PRIOR_RENDER[0]
            context.scene.render.resolution_y = PRIOR_RENDER[1]
        return

    # Render interactively ONLY if there's a single render.
    if len(remaining_renders) <= 1:
        props.render_running = True
        render_next_in_queue(context, interactive=True)
    else:
        props.render_running = True  # Don't trigger handler, manage directly.

        for row in remaining_renders:
            # TODO: order of renders not for sure same technically, for prints.
            if not props.render_running:
                print("Ending render queue early on" + str(row.user_name))
                return
            print("Starting render " + str(row.user_name))
            render_next_in_queue(context, interactive=False)
            single_render_complete(context)
        props.render_running = False  # technically redundant


def render_next_in_queue(context, interactive: bool) -> None:
    """Starts the next (could be first) render, as well as ends and cleanup."""
    props = context.scene.crp_props
    next_id = None

    # get the next not-done id in the queue
    for i, row in enumerate(props.file_list):
        if row.queue_status == READY:
            next_id = i
            break

    if next_id is None:
        print("Nothing left to render")
        props.render_running = False
        setup_large_render(context)  # End with large setup enabled
        return

    props.file_list_index = next_id  # Will trigger load.

    # Now skip if any QC issuers
    # Note: disabled this skip, as it prevents the timer from continuing past
    # any QC-disabled renders.
    # if props.file_list[props.file_list_index].qc_error:
    #     print("Skip render due to QC errors")
    #     return

    # Either way, quickly render the small image
    print(f"Now render {props.file_list[props.file_list_index]}")
    setup_small_render(context)

    # skip handler once to avoid recursive render completion handler trigger.
    global _MID_RENDER
    _MID_RENDER = True
    bpy.ops.render.render('EXEC_DEFAULT',
                          write_still=True,
                          use_viewport=True)
    _MID_RENDER = False

    # Then see about potentially making the full res visually pop up.
    if interactive:
        print("Render interactive; large render only")
        setup_large_render(context)
        bpy.ops.render.render('INVOKE_DEFAULT',
                              write_still=True,
                              use_viewport=True)
    else:
        # Don't do any UI changes after first run
        print("Render batch")
        # bpy.ops.render.render('EXEC_DEFAULT', write_still=True)
        setup_large_render(context)
        bpy.ops.render.render('EXEC_DEFAULT',
                              write_still=True,
                              use_viewport=True)


def single_render_complete(context) -> None:
    """On the completion of a single preview type render, called via handler"""
    props = context.scene.crp_props
    row = props.file_list[props.file_list_index]
    print("Post render processing: id:{} ({})".format(
        props.file_list_index,
        row.user_name))

    # Update row stats accordingly
    row.queue_status = DONE
    row.render_exists = renders_exist_for_row(context, row)
    if not row.render_exists:
        print("Render not found after complete! For: " + row.src_blend)

    # Possible render stats.
    update_scene_stats(context)


def get_large_render_path(context, row) -> str:
    """Given a class instance of submission, return expected path.

    Args:
        row: Instance of FileListProps.
    """
    return _get_generic_render_path(context, row, "render_full")


def get_small_render_path(context, row) -> str:
    """Given a class instance of submission, return expected path.

    Args:
        row: Instance of FileListProps.
    """
    return _get_generic_render_path(context, row, "render_small")


def _get_generic_render_path(context, row, subpath) -> str:
    """Sub function to ensure fetching a consistent style of path.

    Args:
        row: Instance of FileListProps.
        subpath: The sub-folder at the end of the base render output path.
    """
    props = context.scene.crp_props
    base = row.src_blend[:-6]  # To safely drop off ".blend", even if caps.

    # Edge case where user had xyz..blend, but even if the last . is kept,
    # blender render treats the dot as part of suffix, which would cause the
    # addon to think the render doesn't exist even if it does.
    if base[-1] == ".":
        base = base[:-1]
    filename = f"{base}.png"
    # print("Expecting filename: " + filename)
    return bpy.path.abspath(os.path.join(
        props.config_folder, subpath, filename))


def renders_exist_for_row(context, row):
    """Verify if all expected renders exist for a given row."""
    large_exists = os.path.isfile(get_large_render_path(context, row))
    small_exists = os.path.isfile(get_small_render_path(context, row))
    return large_exists and small_exists


def setup_large_render(context):
    """Assign settings for the larger scale render."""
    props = context.scene.crp_props
    row = props.file_list[props.file_list_index]
    outfile = get_large_render_path(context, row)[:-4]  # Drop off .png
    context.scene.render.filepath = outfile

    global PRIOR_RENDER
    if not PRIOR_RENDER:
        PRIOR_RENDER = (
            context.scene.render.resolution_x,
            context.scene.render.resolution_y)
    else:
        context.scene.render.resolution_x = PRIOR_RENDER[0]
        context.scene.render.resolution_y = PRIOR_RENDER[1]
    context.scene.render.resolution_percentage = 100

    obj = bpy.data.objects[AUTHOR_TEXT_OBJ]
    obj.hide_render = False
    obj.hide_viewport = False


def setup_small_render(context):
    """Assign settings for the larger scale render."""
    props = context.scene.crp_props
    row = props.file_list[props.file_list_index]
    outfile = get_small_render_path(context, row)[:-4]  # Drop off .png
    context.scene.render.filepath = outfile

    global PRIOR_RENDER
    if not PRIOR_RENDER:
        PRIOR_RENDER = (
            context.scene.render.resolution_x,
            context.scene.render.resolution_y)

    context.scene.render.resolution_x = props.thumbnail_pixels
    context.scene.render.resolution_y = props.thumbnail_pixels
    context.scene.render.resolution_percentage = 100

    obj = bpy.data.objects[AUTHOR_TEXT_OBJ]
    obj.hide_render = True
    obj.hide_viewport = True


# -----------------------------------------------------------------------------
# Blender Handler events
# -----------------------------------------------------------------------------


@persistent
def crp_render_complete_handler(scene: bpy.types.Scene):
    """Ran on completion of a render."""
    props = bpy.context.scene.crp_props
    if _MID_RENDER:
        return
    if not props.render_running:
        return
    print("Community render frame finished!")

    # trigger subsequent loads if at least one render remaining
    single_render_complete(bpy.context)
    # render_next_in_queue(bpy.context, interactive=False)


# -----------------------------------------------------------------------------
# Operator class registration
# -----------------------------------------------------------------------------


class SCENE_OT_reload(bpy.types.Operator):
    """Open the next file alphabetically in the folder"""
    bl_idname = "crp.reload_list"
    bl_label = "Reload"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        update_source_folder(self, context)
        return {'FINISHED'}


class SCENE_OT_open_previous_file(bpy.types.Operator):
    """Open the next file alphabetically in the folder"""
    bl_idname = "crp.open_previous_file"
    bl_label = "Open next file"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.crp_props
        if props.file_list_index <= 0:
            props.file_list_index = len(props.file_list) - 1
        else:
            props.file_list_index -= 1
        return {'FINISHED'}


class SCENE_OT_open_next_file(bpy.types.Operator):
    """Open the next file alphabetically in the folder"""
    bl_idname = "crp.open_next_file"
    bl_label = "Open next file"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.crp_props
        if props.file_list_index >= len(props.file_list) - 1:
            props.file_list_index = 0
        else:
            props.file_list_index += 1
        return {'FINISHED'}


class SCENE_OT_open_random_file(bpy.types.Operator):
    """Open a random file to view"""
    bl_idname = "crp.open_random_file"
    bl_label = "Open random"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.crp_props
        ind = random.randint(0, len(props.file_list) - 1)
        props.file_list_index = ind
        return {'FINISHED'}


class SCENE_OT_render_open_file(bpy.types.Operator):
    """Render the open file"""
    bl_idname = "crp.render_open_file"
    bl_label = "Render current"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        render_open_file(context)
        return {'FINISHED'}


class SCENE_OT_render_all_files(bpy.types.Operator):
    """Render all files non interactively, having already been prepped"""
    bl_idname = "crp.render_all_files"
    bl_label = "Render all missing"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        queue_all_files(context)
        initiate_render_queue(context)
        return {'FINISHED'}


class SCENE_OT_render_all_interactive(bpy.types.Operator):
    """Render all files, with interactive option to ESC out early"""
    bl_idname = "crp.render_all_interactive"
    bl_label = "Render all missing"
    bl_options = {'REGISTER', 'UNDO'}

    time_start = 0

    def invoke(self, context, event):
        props = context.scene.crp_props
        props.render_running = True
        queue_all_files(context)

        try:
            bpy.app.timers.unregister(render_timer_callback)
        except ValueError:
            pass  # Already removed or doesn't exist.
        bpy.app.timers.register(render_timer_callback,
                                first_interval=0,
                                persistent=False)

        context.window_manager.modal_handler_add(self)

        # Initialize stats to be displayed in UI panel
        global _RENDER_START
        global _RENDER_COUNT
        _RENDER_START = time.time()
        _RENDER_COUNT = 0
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        context.area.tag_redraw()
        props = context.scene.crp_props
        if props.render_running is False:
            print(f"MODAL: Render completed, ending after {_RENDER_COUNT}")
            context.area.header_text_set(None)
            return {'FINISHED'}
        if event.type in {'ESC', 'LEFTMOUSE', 'RIGHTMOUSE'}:
            print(f"MODAL: cancel render after {_RENDER_COUNT}")
            props.render_running = False  # Will finish after the next render.
            context.area.header_text_set(None)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}


class SCENE_OT_mark_qc_error(bpy.types.Operator):
    """Add or replace the saved QC message error, blank for none"""
    bl_idname = "crp.mark_qc_error"
    bl_label = "Assign QC Error"
    bl_options = {'REGISTER', 'UNDO'}

    qc_error = bpy.props.StringProperty(
        name="Error",
        description="Error message text to save")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Enter text to save as the error,")
        layout.label(text="empty=clears error. Use ; between errors.")
        layout.prop(self, "qc_error", text="")

    def execute(self, context):
        props = context.scene.crp_props
        row = props.file_list[props.file_list_index]
        path = qc_error_path(context, row.src_blend)
        if os.path.isfile(path):
            os.remove(path)
        row.qc_error = self.qc_error  # Will auto save next text
        return {'FINISHED'}


class SCENE_OT_delete_render(bpy.types.Operator):
    """Delete the active file's existing renders"""
    bl_idname = "crp.delete_render"
    bl_label = "Delete render"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.crp_props
        row = props.file_list[props.file_list_index]
        fullsize_path = get_large_render_path(context, row)
        thumbsize_path = get_small_render_path(context, row)
        try:
            os.remove(fullsize_path)
        except OSError as err:
            print(f"Error deleting renders: {err}")

        try:
            os.remove(thumbsize_path)
        except OSError as err:
            print(f"Error deleting renders: {err}")

        # Don't just assume it worked, use the same logical check as elsewhere.
        row.render_exists = renders_exist_for_row(context, row)
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# UI definitions
# -----------------------------------------------------------------------------


def qc_error_path(context, src_blend: str) -> str:
    """Return a the path for a given blend file's qc_error file."""
    props = context.scene.crp_props
    subpath = os.path.join(bpy.path.abspath(props.config_folder), "qc_errors")
    if not os.path.isdir(subpath):
        os.mkdir(subpath)
    path = os.path.join(subpath, f"{src_blend}.txt")
    return path


def read_qc_error(self, context) -> Optional[str]:
    """Read the QC error text if any has been saved to disk."""
    path = qc_error_path(context, self.src_blend)
    lines = ""
    if os.path.isfile(path):
        with open(path, 'r') as fd:
            lines = fd.read()
    return lines


def save_qc_error(self, context) -> None:
    """Save out error as txt, not overwriting if one exists already."""
    path = qc_error_path(context, self.src_blend)
    if self.qc_error and not os.path.isfile(path):
        print(f"To save QC error: {path}")
        with open(path, 'w') as fd:
            fd.write(self.qc_error)


def update_source_folder(self, context) -> None:
    """Handler for when the source folder is changed."""
    props = context.scene.crp_props
    props.file_list.clear()
    blend_files = get_blend_file_list(context)
    form_data = load_csv_metadata(context)
    for blend in blend_files:
        row = props.file_list.add()
        row.label = blend.replace(".blend", "")
        row.name = row.label
        row.src_blend = blend
        row.qc_error = read_qc_error(row, context)
        this_data = form_data.get(blend)
        if this_data:
            row.user_name = this_data.get(0) or ""
            row.country = this_data.get(1) or ""

        row.has_form_match = this_data is not None
        row.render_exists = renders_exist_for_row(context, row)

    if not props.file_list:
        print("Error - no files loaded")
        return
    elif props.file_list_index >= len(props.file_list):
        props.file_list_index = len(props.file_list) - 1

    # Finally, load the new view.
    load_active_row(context)


def update_folderset_list_index(self, context) -> None:
    """Handler for when new row is selected, load the given blend."""
    load_active_row(context)


def update_scene_stats(context) -> None:
    """Update global vars for scene stats for UI drawing."""
    global scene_stats
    props = context.scene.crp_props

    # scne_stats = {} Don't fully clear, some will be held over from
    # the form data load
    scene_stats[BLEND_COUNT] = len(props.file_list)
    scene_stats[RENDERED] = len(
        [row for row in props.file_list if row.render_exists])
    scene_stats[NUM_QC_ERR] = len(
        [row for row in props.file_list if row.qc_error])
    scene_stats[NO_FORM_MATCH] = len(
        [row for row in props.file_list if not row.has_form_match])


def update_use_text(self, context) -> None:
    """Toggle whether or not to visually include text (author and country).

    Gracefully continue if the expected text objects are not found.
    """
    props = context.scene.crp_props
    row = props.file_list[props.file_list_index]
    if AUTHOR_TEXT_OBJ:
        txt_user = bpy.data.objects.get(AUTHOR_TEXT_OBJ)
        if not txt_user:
            print(f"Author object not found: {AUTHOR_TEXT_OBJ}")
    else:
        txt_user = None
    if COUNTRY_TEXT_OBJ:
        txt_country = bpy.data.objects.get(COUNTRY_TEXT_OBJ)
        if not txt_country:
            print(f"Author object not found: {COUNTRY_TEXT_OBJ}")
    else:
        txt_country = None

    if txt_user:
        txt_user.hide_render = not props.use_text
        txt_user.hide_viewport = not props.use_text
        if props.use_text:
            txt_user.data.body = row.user_name
        else:
            txt_user.data.body = ""

    if txt_country:
        # Update visibility
        txt_country.hide_render = not props.use_text
        txt_country.hide_viewport = not props.use_text
        if props.use_text:
            txt_country.data.body = row.country.upper()
        else:
            txt_country.data.body = ""


def update_demo_mode(self, context) -> None:
    """Update the timer used for demo mode."""
    props = context.scene.crp_props

    try:
        bpy.app.timers.unregister(demo_timer_callback)
    except ValueError:
        pass  # Already removed or doesn't exist.

    if not props.demo_mode:
        return

    initial_delay = 1
    bpy.app.timers.register(demo_timer_callback,
                            first_interval=initial_delay,
                            persistent=False)


def demo_timer_callback() -> float:
    """Timer function called when demo mode is on."""
    props = bpy.context.scene.crp_props
    if not props.demo_mode:
        return None  # Will unregister the timer automatically.

    SCENE_OT_open_next_file.execute(None, bpy.context)
    return props.demo_interval


class FileListProps(bpy.types.PropertyGroup):
    """List and data structure to check stats of loaded blend submissions."""
    label = bpy.props.StringProperty(default="")
    render_exists = bpy.props.BoolProperty(default=False)
    has_form_match = bpy.props.BoolProperty(default=False)
    qc_error = bpy.props.StringProperty(
        default="", update=save_qc_error)  # Will skip its render.
    qc_warn = bpy.props.StringProperty(default="")  # Will render.
    user_name = bpy.props.StringProperty(default="")
    country = bpy.props.StringProperty(default="")
    src_blend = bpy.props.StringProperty(default="")
    queue_status = bpy.props.EnumProperty(
        name="Queue status",
        items=(
            (NOT_QUEUED, "Not queued", "Not currently queued"),
            (READY, "Ready", "Will render"),
            (DONE, "Done", "Finished render"),
            (SKIP, "Skip", "Don't render"),
        ))


class CRP_UL_source_files(bpy.types.UIList):
    """UI list for drawing loaded blend files."""

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index, flt_flag):
        row = layout.row(align=True)
        row.label(text=item.label)
        if item.qc_error:
            row.label(text="", icon="ERROR")
        elif item.queue_status == READY:
            row.label(text="", icon="CHECKBOX_DEHLT")
        elif item.queue_status == DONE:
            row.label(text="", icon="CHECKBOX_HLT")
        icon = "RESTRICT_RENDER_OFF" if item.render_exists else "RESTRICT_RENDER_ON"
        row.label(text="", icon=icon)


class SceneProps(bpy.types.PropertyGroup):
    """All properties used by this addon, saved with blend file to scene."""
    config_folder = bpy.props.StringProperty(
        name="TSV/Renders",
        description="Folder for render outputs and form_responses.tsv file",
        subtype='DIR_PATH')
    source_folder = bpy.props.StringProperty(
        name="Blends",
        description="Folder containing all blend files",
        subtype='DIR_PATH',
        update=update_source_folder)
    file_list = bpy.props.CollectionProperty(type=FileListProps)
    file_list_index = bpy.props.IntProperty(
        default=0,
        update=update_folderset_list_index)
    render_running = bpy.props.BoolProperty(
        name="Render in progress",
        description="Internal bool used to see if mid render queue",
        default=False)
    load_original = bpy.props.BoolProperty(
        name="Load original",
        description="Load the source, unmodified scene (don't use in render!)",
        default=False,
        update=update_folderset_list_index)
    use_text = bpy.props.BoolProperty(
        name="Use text",
        description="Populate the text in the full-sized renders",
        default=False,
        update=update_use_text)
    demo_mode = bpy.props.BoolProperty(
        name="Demo mode",
        description="Auto progress to next file after (Demo Interval) seconds",
        default=False,
        update=update_demo_mode)
    demo_interval = bpy.props.FloatProperty(
        name="Interval",
        description="Delay between progressing to next blend file",
        default=2.0,
        min=0.5)
    thumbnail_pixels = bpy.props.IntProperty(
        name="Thumbnail size",
        description="Pixel height and width of thumbnail render",
        default=100,
        min=10)

    # Filter properties

    # Enum option of which blend files to load? e.g.:
    # All in folder, all in CSV (grand total), all rendered, all not-rendered


class CRP_PT_CommunityPanel(bpy.types.Panel):
    """Creates a Panel in the Object properties window"""
    bl_label = PROJECT_NAME
    bl_idname = "SCENE_PT_commuity_render"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"

    def draw(self, context):
        props = context.scene.crp_props
        layout = self.layout

        row = layout.row(align=True)
        row.prop(props, "config_folder")

        config_exists = os.path.isdir(bpy.path.abspath(props.config_folder))
        responses_exists = os.path.isfile(get_responses_path(context))
        if not props.config_folder or not config_exists:
            row = layout.row()
            box = row.box()
            col = box.column()
            col.scale_y = 0.8
            col.label(text="Folder not set for TSV/renders,")
            col.label(text="select folder with the .tsv!")
            return
        elif not responses_exists:
            row = layout.row()
            box = row.box()
            col = box.column()
            col.scale_y = 0.8
            col.label(text="Missing the TSV file!")
            col.label(text="Download from forms, place")
            col.label(text="in the 'TSV/Render' folder, named:")
            col.label(text=os.path.basename(get_responses_path(context)))

        row = layout.row(align=True)
        row.prop(props, "source_folder")

        source_exists = os.path.isdir(bpy.path.abspath(props.source_folder))
        if not props.source_folder or not source_exists:
            row = layout.row()
            box = row.box()
            col = box.column()
            col.scale_y = 0.8
            col.label(text="Folder not set for blends,")
            col.label(text="select one above!")
            return

        row = layout.row(align=True)
        row.label(text="Click row to load")
        row.operator(
            SCENE_OT_open_previous_file.bl_idname, text="", icon="TRIA_UP")
        row.operator(
            SCENE_OT_open_next_file.bl_idname, text="", icon="TRIA_DOWN")
        row.operator(SCENE_OT_reload.bl_idname, text="", icon="FILE_REFRESH")

        row = layout.row()
        main_col = row.column()
        main_col.template_list("CRP_UL_source_files", "",
                               props, "file_list",
                               props, "file_list_index")

        if not props.file_list:
            row = layout.row()
            main_col = row.column(align=True)
            main_col.label(text="Nothing loaded - change path!", icon="ERROR")
            return

        main_col.operator(SCENE_OT_open_random_file.bl_idname)
        subrow = main_col.row(align=True)
        subrow.prop(props, "load_original")
        subrow.prop(props, "use_text")

        subrow = main_col.row(align=True)
        cubrowcol = subrow.column()
        cubrowcol.prop(props, "demo_mode")
        cubrowcol = subrow.column()
        cubrowcol.enabled = props.demo_mode
        cubrowcol.prop(props, "demo_interval")


class CRP_PT_RowInfoStats(bpy.types.Panel):
    """Show details for the loaded blend file."""
    bl_label = "Open scene stats"
    bl_parent_id = CRP_PT_CommunityPanel.bl_idname
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"

    def draw(self, context):
        row = self.layout.row()
        col = row.column(align=True)
        col.scale_y = 0.8

        props = context.scene.crp_props
        if not props.file_list:
            col.label(text="(Load item above first)")
            return
        this_row = props.file_list[props.file_list_index]

        col.label(text="ACTIVE ROW STATS", icon="ONIONSKIN_OFF")
        col.label(text=f"Current row: {props.file_list_index+1}")
        col.label(text=f"Blend file: {this_row.src_blend}")
        col.label(text=f"Author: {this_row.user_name} ({this_row.country})")
        col.label(text=f"Found in form: {this_row.has_form_match}")
        col.label(text=f"Rendered: {this_row.render_exists}")

        row = self.layout.row()
        col = row.column(align=True)
        if this_row.qc_error:
            errors = this_row.qc_error.split(";")
            col.label(text="QC errors found", icon="ERROR")
            box = col.box()
            bcol = box.column()
            for err in errors:
                bcol.label(text=err, icon="DOT")

            # TODO: check if edit linked library available.
            if context.object and context.object.instance_collection:
                props = col.operator(
                    "object.edit_linked",
                    icon="LINK_BLEND",
                    text="Edit Library to fix issues")
            ops = col.operator(SCENE_OT_mark_qc_error.bl_idname)
            ops.qc_error = this_row.qc_error
        else:
            col.operator(SCENE_OT_mark_qc_error.bl_idname)
        colrow = col.row(align=True)
        if not this_row.render_exists:
            colrow.enabled = False
        colrow.operator(SCENE_OT_delete_render.bl_idname)

        # Scene stats now

        row = self.layout.row()
        col = row.column(align=True)
        col.scale_y = 0.8
        col.label(text="")
        col.label(text="OVERALL STATS", icon="ONIONSKIN_ON")
        bcount = scene_stats.get(BLEND_COUNT, 1)
        col.label(
            text=f"Blends: {bcount} (non blend: {scene_stats.get(NON_BLEND)})")
        perc = scene_stats.get(RENDERED, 0) / bcount
        perc *= 100
        col.label(
            text=f"Rendered: {scene_stats.get(RENDERED)} ({perc:.2f}%)")

        perc = scene_stats.get(NUM_QC_ERR, 0) / bcount
        perc *= 100
        col.label(
            text=f"QC fails: {scene_stats.get(NUM_QC_ERR)} ({perc:.2f}%)")

        perc = scene_stats.get(NO_FORM_MATCH, 0) / bcount
        perc *= 100
        no_match = scene_stats.get(NO_FORM_MATCH)
        col.label(text=f"No form match: {no_match} ({perc:.2f}%)")


class CRP_PT_RenderInfo(bpy.types.Panel):
    """Panel to manage renders."""
    bl_label = "Render"
    bl_parent_id = CRP_PT_CommunityPanel.bl_idname
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"

    def draw(self, context):
        props = context.scene.crp_props

        col = self.layout.column()

        if props.render_running:
            runtime = format_seconds(time.time() - _RENDER_START)
            col.label(text=f"Rendered {_RENDER_COUNT} | {runtime}")
            col.alert = True
            col.prop(props, "render_running",
                     text="Cancel render (esc)", icon="X")
            return

        col.prop(props, "thumbnail_pixels")
        col.label(text="(full size uses scene settings)")
        col.operator(SCENE_OT_render_open_file.bl_idname)
        # col.operator(SCENE_OT_render_all_files.bl_idname)
        col.operator(SCENE_OT_render_all_interactive.bl_idname)
        col.label(text="(delete renders to re-do)")


classes = (
    FileListProps,
    SceneProps,
    CRP_PT_CommunityPanel,
    CRP_PT_RowInfoStats,
    CRP_PT_RenderInfo,
    CRP_UL_source_files,
    SCENE_OT_reload,
    SCENE_OT_open_previous_file,
    SCENE_OT_open_next_file,
    SCENE_OT_open_random_file,
    SCENE_OT_render_open_file,
    SCENE_OT_render_all_files,
    SCENE_OT_render_all_interactive,
    SCENE_OT_mark_qc_error,
    SCENE_OT_delete_render,
)


def register():
    """Register operator functions and properties."""
    for cls in classes:
        make_annotations(cls)
        bpy.utils.register_class(cls)

    bpy.types.Scene.crp_props = bpy.props.PointerProperty(type=SceneProps)
    if crp_render_complete_handler not in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.append(crp_render_complete_handler)
        print("Enabled handler for render complete")
    else:
        print("Fatal! Could not register the render completion handler")


def unregister():
    """Unregister script."""
    if crp_render_complete_handler in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.remove(crp_render_complete_handler)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
