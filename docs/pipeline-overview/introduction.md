# Introduction

::: warning Work in Progress
4 May 2023 - The content of this page is currently being edited/updated.
:::

The goal of this documentation is to describe the pipeline and IT setup used at Blender Studio, in a way that can be replicated in another environment from scratch.

## How to read/write the docs

The documentation features two types of content:

* **Design docs**: explanations and insight on why things are built in a certain way
* **Guides**, for two audiences:
  * users/artists learning how to perform certain workflows
  * TDs learning how to deploy and maintain the pipeline in a production environment


## Design Docs

* Design principles (use Blender as much as possible, use add-ons only when needed, rely on Blender's linking system)
* Breakdown per department/workflow
  * Editorial/previz
  * Concept design
  * Caracter creation
    * Modeling
    * Shading
    * Rigging
  * Animation pipeline
  * Shot assembly (shot builder)
  * Task review
  * Shading and lighting pipelines
  * Rendering pipeline
  * Coloring

These topics can be described at a high-level, and *reference* specific tools, add-ons and worfklows in a dedicated section.


## Guides

* Workstation manual
* Workflows (like Design Docs above, but the practical steps). Depending on the type of production, workflows often need to be changed and tweaked. That part can better be documented on the Blender Studio blog.
* Media Viewer
* Infrastructure setup (how to build a studio from scratch)

For "external" tools like Flamenco or Kitsu, the idea is to explain the specific use or customization we do a Blender Studio and refer to the official documentation for the rest. For example: "Install Kitsu by following the official guide".