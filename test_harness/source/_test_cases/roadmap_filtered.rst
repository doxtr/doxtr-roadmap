Filtered Roadmap
================

This test case exercises ``:tags:`` and ``:period:`` filtering.

Tags filter — only "eng" rows
------------------------------

.. roadmap::
   :title: Engineering Tasks Only
   :tags: eng

   section,name,start,end,row_group,link,tags
   Periods,Set27-01,2026-11-09,2027-01-29,,,
   Periods,Set27-04,2027-02-01,2027-04-09,,,
   Work,Platform Migration,2026-12-01,2027-04-30,,,eng
   Work,Security Audit,2027-01-15,2027-01-29,,,security
   Work,API Redesign,2027-02-15,2027-06-01,,,eng code

Period zoom — Set27-01 only
----------------------------

.. roadmap::
   :title: Set27-01 Zoom
   :period: Set27-01

   section,name,start,end,row_group,link,tags
   Periods,Set27-01,2026-11-09,2027-01-29,,,
   Periods,Set27-04,2027-02-01,2027-04-09,,,
   Work,Platform Migration,2026-12-01,2027-04-30,,,eng
   Work,Security Audit,2027-01-15,2027-01-29,,,security
