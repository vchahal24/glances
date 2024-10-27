.. _disk:

Disk I/O
========

.. image:: ../_static/diskio.png

Glances displays the disk I/O throughput. The unit is adapted
dynamically.

You can display:

- bytes per second (default behavior / Bytes/s, KBytes/s, MBytes/s, etc)
- requests per second (using --diskio-iops option or *B* hotkey)

There is no alert on this information.

It's possible to define:

- a list of disk to show (white list)
- a list of disks to hide
- aliases for disk name

under the ``[diskio]`` section in the configuration file.

For example, if you want to hide the loopback disks (loop0, loop1, ...)
and the specific ``sda5`` partition:

.. code-block:: ini

    [diskio]
    hide=sda5,loop.*

or another example:

.. code-block:: ini

    [diskio]
    show=sda.*

Filtering is based on regular expression. Please be sure that your regular
expression works as expected. You can use an online tool like `regex101`_ in
order to test your regular expression.

You also can automatically hide disk with no read or write using the
``hide_zero`` configuration key. The optional ``hide_threshold_bytes`` option
can also be used to set a threshold higher than zero.

.. code-block:: ini

    [diskio]
    hide_zero=True
    hide_threshold_bytes=0

.. _regex101: https://regex101.com/