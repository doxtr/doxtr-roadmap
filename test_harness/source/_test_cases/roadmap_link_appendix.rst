Link Appendix Test
==================

This test case exercises the ``link_appendix`` feature.  The chart below has
two tasks with plain ``https://`` links and one task with no link.

The harness ``conf.py`` sets ``doxtr_roadmap_link_appendix = "list"`` and
``doxtr_roadmap_link_appendix_builders = ["html"]``, so both the plantuml
image and a bullet-list appendix of clickable links should appear in the
HTML output.

.. roadmap::
   :title: Link Appendix Demo
   :scale: monthly
   :start: 2027-01-01

   section,name,start,end,row_group,link,tags
   Tools,PlantUML Upgrade,2027-01-01,2027-02-28,,https://plantuml.com,eng
   Tools,Sphinx Migration,2027-02-01,2027-03-31,,https://www.sphinx-doc.org,eng code
   Tools,Internal Task,2027-03-01,2027-04-30,,,ops
