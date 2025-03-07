import os
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image, UnidentifiedImageError
from jinja2 import Environment, Template

# Configure logging
logging.basicConfig(
    filename="stl_catalog_errors.log",
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


def copy_and_resize_image(original_path: Path, local_image_path: Path, max_size=(300, 300)):
    """
    Copy and resize a single image if needed, with robust error handling.
    Returns the local thumbnail path if successful, or None if failed.
    """
    try:
        # Only regenerate the thumbnail if the original is newer or if the thumbnail doesn't exist
        if (not local_image_path.exists() or
                original_path.stat().st_mtime > local_image_path.stat().st_mtime):
            with Image.open(original_path) as img:
                img.thumbnail(max_size)
                img.save(local_image_path)
            print(f"Resized and copied image: {original_path} -> {local_image_path}")
        return str(local_image_path)
    except UnidentifiedImageError:
        logging.error(f"Unidentified image file: {original_path}")
        print(f"Error: Cannot process image {original_path}. Logged to file.")
    except PermissionError:
        logging.error(f"Permission error while accessing {original_path}")
        print(f"Error: Permission denied for {original_path}. Logged to file.")
    except Exception as e:
        logging.error(f"Error processing {original_path}: {str(e)}")
        print(f"Error: {str(e)} - Logged to file.")

    return None


def copy_and_resize_images(catalog, img_folder: Path, max_size=(300, 300), max_workers=4):
    """
    For each image in the catalog, create a thumbnail in `img` folder.
    We keep track of both the full-sized original and the thumbnail path in the model data.
    Uses concurrency to speed up the process.
    """
    if not img_folder.exists():
        img_folder.mkdir(parents=True, exist_ok=True)

    future_to_meta = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for base_path, creators in catalog.items():
            for creator, releases in creators.items():
                for release, models in releases.items():
                    for model_name, data in models.items():
                        # The 'images_original' list is the full-sized paths
                        # The 'images_thumbs' list will hold the thumbnail paths
                        data.setdefault("images_original", [])
                        data.setdefault("images_thumbs", [])

                        # We move anything from "images" into "images_original"
                        # so we maintain them side-by-side
                        if "images" in data:
                            # In case we haven’t already set them aside
                            for img_path in data["images"]:
                                original_path = Path(img_path)
                                if original_path.exists() and original_path.is_file():
                                    # Schedule thumbnail creation
                                    local_image_path = img_folder / original_path.name
                                    future = executor.submit(
                                        copy_and_resize_image,
                                        original_path,
                                        local_image_path,
                                        max_size
                                    )
                                    # Map the future to (model, original image path)
                                    future_to_meta[future] = (data, original_path)
                            # Clear out "images" to avoid confusion
                            data["images"] = []

    # Gather the results for the thumbnails
    for future in as_completed(future_to_meta):
        data, original_path = future_to_meta[future]
        thumb_path = future.result()
        if thumb_path:
            # Store both the original path and thumbnail path
            data["images_original"].append(str(original_path))
            data["images_thumbs"].append(thumb_path)


def scan_directories(base_paths):
    """
    Scans multiple directories recursively, categorizing STL-related files.
    We use the folder structure to guess Creator -> Release -> Model,
    but we also do some special cases:
      - If a file is .zip, we force 'release' = 'Zip'.
      - .lys / .chitubox = slicer files
      - .stl = typical 3D model
      - .jpg / .png = images
      - If we can't determine a model name, use the folder name.
    """
    catalog = {}

    for base_path_str in base_paths:
        base_path = Path(base_path_str).resolve()
        print(f"Starting directory scan: {base_path}")

        for root, _, files in os.walk(base_path):
            root_path = Path(root)
            relative_path = root_path.relative_to(base_path)
            parts = relative_path.parts

            # Attempt to pick out the "creator", "release", "model"
            # If we don't have enough directory depth, we default in a safe way.
            if len(parts) < 1:
                creator = "Misc Files"
                release = ""
                model_name = root_path.name
            else:
                creator = parts[0] if len(parts) >= 1 else "Misc Files"
                # By default, release is the second part if it exists, else "Unknown Release"
                release = parts[1] if len(parts) >= 2 else "Unknown Release"
                # For model name, if we don't have 3+ parts, fallback to the folder's name
                if len(parts) >= 3:
                    model_name = parts[-1]
                else:
                    model_name = root_path.name

            # Ensure the base path is in the catalog
            if base_path_str not in catalog:
                catalog[base_path_str] = {}
            if creator not in catalog[base_path_str]:
                catalog[base_path_str][creator] = {}
            if release not in catalog[base_path_str][creator]:
                catalog[base_path_str][creator][release] = {}
            if model_name not in catalog[base_path_str][creator][release]:
                catalog[base_path_str][creator][release][model_name] = {
                    "stl_files": [],
                    "slicer_files": [],
                    "files": [],  # For "other" stuff
                    "images": []
                }

            print(f"Scanning folder: {relative_path}")
            # Now categorize each file in the current folder
            for filename in files:
                file_path = root_path / filename
                if not file_path.is_file():
                    continue

                ext = file_path.suffix.lower().lstrip('.')

                # If it's a .zip, override the release to "Zip"
                if ext == "zip":
                    release_key = "Zip"
                    if release_key not in catalog[base_path_str][creator]:
                        catalog[base_path_str][creator][release_key] = {}
                    if model_name not in catalog[base_path_str][creator][release_key]:
                        catalog[base_path_str][creator][release_key][model_name] = {
                            "stl_files": [],
                            "slicer_files": [],
                            "files": [],
                            "images": []
                        }
                    # Insert .zip file as a normal "file"
                    catalog[base_path_str][creator][release_key][model_name]["files"].append(str(file_path))

                elif ext in ["jpg", "jpeg", "png"]:
                    catalog[base_path_str][creator][release][model_name]["images"].append(str(file_path))

                elif ext in ["lys", "chitubox"]:
                    catalog[base_path_str][creator][release][model_name]["slicer_files"].append(str(file_path))

                elif ext in ["stl"]:
                    catalog[base_path_str][creator][release][model_name]["stl_files"].append(str(file_path))

                else:
                    # Catch-all for other stuff
                    catalog[base_path_str][creator][release][model_name]["files"].append(str(file_path))

    print("Directory scan complete.")
    return catalog


def remove_empty_entries(catalog: dict) -> dict:
    """
    Removes empty models, releases, creators, and base_paths
    from the catalog structure in-place.
    Returns the pruned catalog reference.
    """
    empty_base_paths = []
    for base_path, creators in catalog.items():
        empty_creators = []

        for creator, releases in creators.items():
            empty_releases = []
            for release, models in releases.items():
                empty_models = []
                for model, data in models.items():
                    # Check if this model is truly empty
                    # i.e. no stl_files, no images, no slicer_files, no "files"
                    if (not data["stl_files"] and
                            not data["slicer_files"] and
                            not data["images"] and
                            not data["files"] and
                            not data.get("images_original") and
                            not data.get("images_thumbs")):
                        empty_models.append(model)

                for em in empty_models:
                    del models[em]

                if not models:
                    empty_releases.append(release)

            for er in empty_releases:
                del releases[er]

            if not releases:
                empty_creators.append(creator)

        for ec in empty_creators:
            del creators[ec]

        if not creators:
            empty_base_paths.append(base_path)

    for ebp in empty_base_paths:
        del catalog[ebp]

    return catalog


def generate_html(catalog, output_file: Path):
    """
    Generates an HTML file displaying the categorized STL models
    using Bootstrap 5. For each model, we show:
      - Prefer slicer files, displayed first.
      - Then STL files.
      - Then 'other' files
      - Thumbnails (click to open full image in new window).
      - A link to open the containing folder instead of the individual file.
    """

    template_str = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
    <title>STL Catalog</title>

    <!-- Bootstrap 5 CSS -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
          rel="stylesheet"
          integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH"
          crossorigin="anonymous">
    <style>
        .model img {
            margin-right: 10px;
            margin-bottom: 10px;
            border: 1px solid #ccc;
        }
        .slicer-file {
            font-weight: bold;
            color: red;
        }
        .file-list {
            margin-top: 0.5rem;
        }
        /* Floating Back to Top Button */
        #backToTopBtn {
            display: none;
            position: fixed;
            bottom: 40px;
            right: 40px;
            z-index: 99;
        }
    </style>
</head>
<body class="bg-light">
    <div class="container my-5">
        <h1 class="mb-4">STL Catalog</h1>

        <!-- Collapse All button -->
        <button onclick="collapseAllAccordions()" class="btn btn-outline-secondary mb-4">
            Collapse All
        </button>

        <!-- Outer accordion for Base Directories -->
        <div class="accordion" id="accordionBaseDirs">
            {% for base_path, creators in catalog.items() %}
            <div class="accordion-item">
                <h2 class="accordion-header" id="heading-{{ loop.index }}">
                    <button class="accordion-button collapsed"
                            type="button"
                            data-bs-toggle="collapse"
                            data-bs-target="#collapse-{{ loop.index }}"
                            aria-expanded="false"
                            aria-controls="collapse-{{ loop.index }}">
                        Base Directory: {{ base_path }}
                    </button>
                </h2>
                <div id="collapse-{{ loop.index }}"
                     class="accordion-collapse collapse"
                     aria-labelledby="heading-{{ loop.index }}"
                     data-bs-parent="#accordionBaseDirs">
                    <div class="accordion-body">

                        <!-- Nested accordion for Creators -->
                        <div class="accordion" id="accordionCreators-{{ loop.index }}">
                            {% for creator, releases in creators.items() %}
                            <div class="accordion-item">
                                <h2 class="accordion-header" id="heading-{{ loop.index }}-{{ loop.index0 }}">
                                    <button class="accordion-button collapsed"
                                            type="button"
                                            data-bs-toggle="collapse"
                                            data-bs-target="#collapse-{{ loop.index }}-{{ loop.index0 }}"
                                            aria-expanded="false"
                                            aria-controls="collapse-{{ loop.index }}-{{ loop.index0 }}">
                                        {{ creator }}
                                    </button>
                                </h2>
                                <div id="collapse-{{ loop.index }}-{{ loop.index0 }}"
                                     class="accordion-collapse collapse"
                                     aria-labelledby="heading-{{ loop.index }}-{{ loop.index0 }}"
                                     data-bs-parent="#accordionCreators-{{ loop.index }}">
                                    <div class="accordion-body">

                                        <!-- Another accordion for Releases -->
                                        <div class="accordion" id="accordionReleases-{{ loop.index }}-{{ loop.index0 }}">
                                            {% for release, models in releases.items() %}
                                            <div class="accordion-item">
                                                <h2 class="accordion-header"
                                                    id="heading-{{ loop.index }}-{{ loop.index0 }}-{{ loop.index1 }}">
                                                    <button class="accordion-button collapsed"
                                                            type="button"
                                                            data-bs-toggle="collapse"
                                                            data-bs-target="#collapse-{{ loop.index }}-{{ loop.index0 }}-{{ loop.index1 }}"
                                                            aria-expanded="false"
                                                            aria-controls="collapse-{{ loop.index }}-{{ loop.index0 }}-{{ loop.index1 }}">
                                                        {{ release if release else 'Misc Files' }}
                                                    </button>
                                                </h2>
                                                <div id="collapse-{{ loop.index }}-{{ loop.index0 }}-{{ loop.index1 }}"
                                                     class="accordion-collapse collapse"
                                                     aria-labelledby="heading-{{ loop.index }}-{{ loop.index0 }}-{{ loop.index1 }}"
                                                     data-bs-parent="#accordionReleases-{{ loop.index }}-{{ loop.index0 }}">
                                                    <div class="accordion-body">
                                                        <!-- Models Listing -->
                                                        {% for model, data in models.items() %}
                                                        <div class="model mb-3">
                                                            <h5 class="fw-bold">{{ model }}</h5>
                                                            <div class="file-list">
                                                                <p class="text-muted mb-1">Files:</p>
                                                                <ul class="list-unstyled">
                                                                    <!-- Show slicer files first -->
                                                                    {% for s in data.get("slicer_files", []) %}
                                                                    <li class="slicer-file">
                                                                        <!-- Link to open folder instead of the file -->
                                                                        <a href="file://{{ s|dirname }}"
                                                                           target="_blank">
                                                                            [Open Folder]
                                                                        </a>
                                                                        - {{ s }}
                                                                    </li>
                                                                    {% endfor %}

                                                                    <!-- Then STL files -->
                                                                    {% for stl in data.get("stl_files", []) %}
                                                                    <li>
                                                                        <a href="file://{{ stl|dirname }}"
                                                                           target="_blank">
                                                                            [Open Folder]
                                                                        </a>
                                                                        - {{ stl }}
                                                                    </li>
                                                                    {% endfor %}

                                                                    <!-- Then general 'other' files -->
                                                                    {% for f in data.get("files", []) %}
                                                                    <li>
                                                                        <a href="file://{{ f|dirname }}"
                                                                           target="_blank">
                                                                            [Open Folder]
                                                                        </a>
                                                                        - {{ f }}
                                                                    </li>
                                                                    {% endfor %}
                                                                </ul>
                                                            </div>
                                                            <div>
                                                                <!-- Image thumbnails that link to full-size images -->
                                                                {% for i in range(data.get("images_thumbs", [])|length) %}
                                                                    {% set thumb = data.images_thumbs[i] %}
                                                                    {% set orig = data.images_original[i] %}
                                                                    <a href="file://{{ orig }}" target="_blank">
                                                                        <img src="{{ thumb }}" width="150" loading="lazy" class="border">
                                                                    </a>
                                                                {% endfor %}
                                                            </div>
                                                        </div>
                                                        {% endfor %}
                                                    </div>
                                                </div>
                                            </div>
                                            {% endfor %}
                                        </div> <!-- End accordionReleases -->

                                    </div>
                                </div>
                            </div>
                            {% endfor %}
                        </div> <!-- End accordionCreators -->

                    </div>
                </div>
            </div>
            {% endfor %}
        </div> <!-- End accordionBaseDirs -->
    </div> <!-- container -->

    <!-- Back to Top Button -->
    <button id="backToTopBtn" class="btn btn-primary" title="Go to top" onclick="topFunction()">
        ↑ Top
    </button>

    <!-- Bootstrap Bundle JS -->
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"
            integrity="sha384-YvpcrYf0tY3lHB60NNkmXc5s9fDVZLESaAA55NDzOxhy9GkcIdslK1eN7N6jIeHz"
            crossorigin="anonymous"></script>

    <script>
        // Show/hide Back to Top button upon scrolling
        const backToTopBtn = document.getElementById("backToTopBtn");
        window.addEventListener("scroll", () => {
            if (document.documentElement.scrollTop > 300) {
                backToTopBtn.style.display = "block";
            } else {
                backToTopBtn.style.display = "none";
            }
        });

        // Scroll to top smoothly
        function topFunction() {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }

        // Collapse all open accordions
        function collapseAllAccordions() {
            const openAccordions = document.querySelectorAll('.accordion-collapse.show');
            openAccordions.forEach(collapseEl => {
                const bsCollapse = bootstrap.Collapse.getOrCreateInstance(collapseEl);
                bsCollapse.hide();
            });
        }
    </script>
</body>
</html>
    """

    # We use a small Jinja2 Environment to define a custom filter for "dirname"
    env = Environment()
    env.filters["dirname"] = lambda path_str: str(Path(path_str).parent)

    template = env.from_string(template_str)
    html_content = template.render(catalog=catalog)
    output_file.write_text(html_content, encoding="utf-8")
    print(f"HTML catalog generated: {output_file}")


def main():
    """
    Main function to execute the directory scan, resize images, and generate the HTML catalog.
    """
    base_paths_input = input("Enter the paths to your STL collections (comma-separated): ").strip()
    base_paths = [p.strip() for p in base_paths_input.split(',')]
    output_file = Path("stl_catalog.html")
    img_folder = Path("img")

    print("Starting STL catalog generation...")
    catalog = scan_directories(base_paths)
    catalog = remove_empty_entries(catalog)
    copy_and_resize_images(catalog, img_folder)
    # Generate HTML
    generate_html(catalog, output_file)

    # If you want to run twice as in the original for safety, you can do so:
    # copy_and_resize_images(catalog, img_folder)
    # generate_html(catalog, output_file)

    print("Process completed successfully!")


if __name__ == "__main__":
    main()
