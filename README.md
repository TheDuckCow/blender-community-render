# Blender Community Render

This Blender 3d python add-on helps load and render blend files in bulk such as
from a community collaboration.

This add-on was built and primarily used in Blender 2.90 and 2.93, but may work
as far back as blender 2.80.

This project was built with scale in mind, to the tune of being able to load,
process, and render 10,000's of blend files. Many of the choices made in
structure and architecture were to improve reliability and consistency, and to
minimize / better handle blender crashes.


## What is this add-on good for?

If you are hosting a community project, where artists submit to you their blend
files, and you need a way to standardize the output (render, library linking,
etc).

The key features of this add-on include:

- Quickly load and cycle through user-submitted blend files.
- Safeguard against any unique user set ups, including blocking python
  scripts from user files from running (which would be a security concern for
  the person using this add-on and loading files on their machine).
    - After using this add-on, you may want to manually re-enable auto-run
    python scripts in user preferences, if you normally enable this.
- Standardize outputs, so that you may render submissions in a way that will
  work with the project output.
- Configure to meet project needs. This is the note for developers: this add-on
  serves as a good **starting point** for customizing for another unique
  community render project.
    - The add-on on it's own probably will never be well suited for a project
    other than the sample default use case.
    - This is because the add-on works best when making specific assumptions
    about desired inputs and similarly, the desired output.
    - That being said, it's far better to start with a solid beginning point
    and likely you can reuse many of the same utility functions.
    - Over time, sample branches/releases may be created for different use cases
    where it has been tailored to meet specific community project needs.

The use case this was built for was to render out an individual pair of frames
(high res and low res) per individual blend file, but the system could be
adjusted for other use cases by adjusting the `process` function as needed.


## Installing

### Option 1: Install for future reuse

This add-on takes the form of a single python (`.py`) file. You can install it
under Edit > User Preferences, Add-ons > Install from file. After installing, be
sure to tick the box to enable the add-on. Save user preferences to ensure it is
automatically enabled the next time you start Blender.

### Option 2: One-time load

Instead of installing the script (especially if continually tweaking), you can
temporarily use the add-on without installing it, by dragging and dropping the
`blender-community-render.py` file into blender's text editor. Press the play
button (or hover over the text and press `alt p`).

## Using the add-on

Now that the add-on is enabled, you can find the community render panel under
the `Scene` tab of the Properties window. This is the tab where the icon (in
Blender 2.9) looks like an upside-down cone. This panel contains all features 
of the add-on.


### Load form responses

An assumption of this add-on is that user submissions are coming from something
like a Google Form (including a file uploader). The add-on looks for a
`form_responses.tsv` file, which is a tab-separated-value download of the raw
form responses. Tabs are used instead of spaces, toa void issues with escaping
commas in CSV tables, and to avoid using other more verbose formats like json.

See the section on preparing this tsv file. This step is really only required
if you are hoping to create in-render text of the author and their country, or
if you want to output filenames based on a different field coming from the form
(such as the drive file id itself) instead of the source uploaded filename.

While there will be warnings if the tsv file is not found, the addon still works
perfectly fine without it.


### Load blend files in Blender

Press the folder icon on the second property in the Community Render panel. It
will automatically load any and all .blend files in that folder.

Conveniently, this actually works *ok-ish* with fuse files too. So for instance
if didn't want to directly download all blend files from e.g. the Google Drive
output folder, you could use something like Drive or Desktop to mount that
folder as a network drive. That being said, things will be more stable and
generally faster if you are able to directly download the whole folder and save
to a custom folder location. In my experience using Drive for Desktop, there is
surprisingly little speed gains to marking the folder to be 'available offline',
copying the whole folder to another local location will work better and be more
stable.

Anecdotally, I also find that loading 10,000's of files to go faster on Mac OSX
than on windows. This is true both on confirming the folder to load, but also
even when simply using blender's built in filebrowser, if navigate into the
folder that has the 10k+ files. Some tricks are used to speed up the loading,
such as caching file listings, but slow is slow. Consider opening a console
window so you can at least monitor the % completion of loading, so you know
it's still working.

### Preparing the form responses

Assuming the submissions are done with Google Forms, the form itself would
include fields such as (titles/order do not matter here)
- Name
- Country
- The blend file upload
- Some kind of affirmation that permission is given to use info + blend
- *Other fields are optional, but could be used to de-duplication repeat entries*

To view submissions, you can generate a spreadsheet of responses. Create a new
spreadsheet, and then you'll likely want to create a new tab which is separate
from the form responses tab. This is because the field names need to have any
tab characters removed prior to download, to avoid breaking the format. 

The actual fields expected in the `form_responses.tsv` file are the following
(order of columns does not matter here, extra columns are fine too):
- full_name: Directly from form, used to display as text.
- country: Directly from form, used to display as text.
- blend_filename: Not actually provided by the Google Drive form. Use either an
  app script or manually join in the name of the blend files based on the drive
  file url (which *is* provided by the form output). This is used to join an
  actual blend file on disk to this row of metadata. See the `drive_name.gs`
  which was used for this purpose.

Final step is to download this form_responses tab as a tsv file, which you can
do so from: file > download > Tab-separated values (.tsv, current sheet).

The sheet you download should be in this format:

![Sample form structure](/sample_form_download.png?raw=true)

### Using the auto-restart scripts

**How it's set up**

Although great effort was put to ensure that blender didn't crash when loading
blend files, it still was inevitable when considering the wide array of blender
versions used for the submitted files. In practice, blender would typically
crash after around 1K blends, but it more had to do with the files submitted.

There are two categories of crashes relevant here:
1. Random, one-off crashes: Meaning, if the blend file that caused the crash
were opened again, it would be fine. True cause could be due to memory leak or
some other random, non-file related issue.
2. Persistent file issue: There are some blend files that, no matter what,
instant-crash blender when loaded. These should not hold back the rest of the
renders from being done, but rather be logged as a "QC error".

The idea behind the crash restarting script is that before loading any blend
file, the addon writes a text file to disk. After loading and transforming this
file, the addon deletes this text file. Thus, if the file exists and blender
has closed, it means it crashed (as opposed to a manual / intentional closing
of blender). Thus, the `render_osx_wrapp.sh` or the `render_windows_wrapper.bat`
wrapper scripts check for this file to know whether to attempt to re-open
blender and resume rendering.

In the two crash categories above, we want to recover and be able to render
(1), but not get stuck in a forever loop when trying to reopen blender to
render (2). Thus, a default of max 3-crashes per blend file is used. That is,
if a blend file causes blender to crash three times, it will permanently skip
it. 

The addon automatically detects even a single crash and logs it as a QC error,
incrementing the number each time, so you can see where files may have happened
to cause a crash but rendered correctly the second time, vs those permanent
failures. 

**Using the startup wrapper**

1. Firstly, choose the script you are going to use: `render_osx_wrapper.sh` for Mac (Linux should work with at most minor modifications), or `render_windows_wrapper.bat` for windows machines.
2. Update the following paths in the wrapper script:
    - blender: The absolute path to the blender executable.
    - src_files: The absolute path to the folder containing all the blend files
    - render_template: The link to the starting template file, a sample of which
      in this repo is [render_template.blend]().
    - addon_py: The relative path to the addon script, ie the [community_render.py]()
      file, which is used if the addon is not already installed and set up in blender
      by default. Note: Due to some loading issues in blender 2.93, it's better
      to just install the script as an addon.
3. Make sure the render_template.blend file has been saved where the tsv path
   is a valid one to the folder containing the tsv file of form responses. This
   will also be the folder where outputs renders are saved (into subfolders).
    - To make your life easy, consider just placing the blend file in the same
    folder as the tsv file, and ensure the template blend file has the "tsv"
    path set to "//", ie the current directory.
4. Open the Terminal (Mac/Linux) or the Command Prompt (Windows), and change into
the folder that contains the `startup.py` script and the according
`render_*_wrapper.*` file. Execute the `render_*_wrapper.*` file.
    - The `startup.py` script is used as a script passed into the background
    blender process, and pretty much just issues the "resync progress" and
    "start render" operations).
5. If you need to end it early, you will need to force quit the script.
Quitting blender itself will, by nature of this restart wrapper, just result in
blender being re-opened a few moments later (also known as "working as
intended"). Force quite typically works by pressing control-c in the terminal
or command prompt window, closing the window, or through the Force Quit Menu
(Mac)/Kill command (Mac/Linux)/Task Manager (Windows).

## Adjusting the script for other use cases/behavior

This script is effectively largely because it makes bespoke assumptions about
the use case at hand. This means that, when applied to other projects, the code
should be adjusted.

The `def process_open_file(context)` function is where you can most easily do
this. This function is called once per blend file when that row is selected, or
during render when it gets to that blend file. This code runs after the entire
blend file has been loaded in as (linked) scene. A simple default use case is
provided with the commented out `process_generic_scene` function. The
donut-rendering use case is covered with the `process_as_donut` function. You
can try creating your own function by modifying either of these, or creating a
new function all together.

## Contributing

Contributions are welcome! See [`CONTRIBUTING.md`](CONTRIBUTING.md) for details.

## License

GPL3; see [`LICENSE`](LICENSE) for details.

## Disclaimer

This project is not an official Google project. It is not supported by
Google and Google specifically disclaims all warranties as to its quality,
merchantability, or fitness for a particular purpose.
