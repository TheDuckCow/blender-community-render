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

"""Script to load and run the main community script, and then start render.

Meant to be used with the {platform}_wrapper executable, to auto-restart
blender if/when it crashes.
"""

import os
import sys

import bpy


if __name__ == '__main__':
	args = (sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
	print("Launching scirpt with args: ", args)

	# Expecting to get flags for:
	if "-src_files" in args:
		ind = args.index("-src_files") + 1
		print("Src path:", args[ind])
		src_files = args[ind]
	else:
		src_files = None

	if "-addon_py" in args:
		ind = args.index("-addon_py") + 1
		print("Addon code:", args[ind])
		addon_py = args[ind]
	else:
		addon_py = None

	if not addon_py or not src_files:
		print(f"Missing addon_py ({addon_py}) or blends ({src_files})")
		sys.exit()

	# Attempt to load the addon from disk if not already installed and enabled.
	if "crp_props" not in dir(bpy.context.scene):
		print("Registering addon...")
		text = bpy.data.texts.load(addon_py)
		mod = text.as_module()
		try:
			mod.register()
		except Exception as err:
			# In blender 2.93, it seems to fail due to some typing/annotation
			# issues, even though it runs fine when run through the UI directly.
			# Likely due to how Blender has implemented annotations, being not
			# actual python standard.
			print(err)

			# This method apparently matches the built-in run_script operator.
			print("Attempting to recover from mod register error using exec:")
			exec(compile(open(addon_py).read(), addon_py, 'exec'))
	else:
		print("Addon alrady enabled")
		# Seems we need to have addon already enabled, otherwise the load-text
		# and register seems to not properly register operators for calls.

	print("Community code: Loading files...")
	props = bpy.context.scene.crp_props
	props.config_folder = os.getcwd()  # For form and setting output location.
	if src_files[-1] != os.path.sep:
		src_files += os.path.sep
	props.source_folder = src_files  # Will trigger reload of all blend files.

	if not props.file_list:
		print("No rows loaded, exiting")
		sys.exit()

	print("Starting render!")
	# bpy.ops.crp.render_all_interactive() # Interactive won't work, as a modal.
	bpy.ops.crp.render_all_files()

	# Try to remove the file which keeps blender restarting.
	print("Renders finished!")
	os.remove("restart_until_finished.txt")
	# sys.exit() # Un-comment to auto-close blender when done rendering.
