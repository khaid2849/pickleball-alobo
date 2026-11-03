{
    'name': 'Pickleball Team — Alobo Integration',
    'version': '18.0.1.2.0',
    'category': 'Sports',
    'summary': 'Bridge that adds Alobo booking features to Pickleball Team: court '
               'sync, availability search, booking schedules and bot commands.',
    'description': """
Pickleball Team — Alobo Integration
===================================
Bridge module between **Pickleball Team** and **Alobo Connector**. It carries
every feature that needs both: court sync from Alobo, the find-available-courts
and court-schedule wizards, the ``/findcourt`` ``/court`` ``/courtplan`` bot
commands, the AI court tools, the session court-search button and a live
availability check on the weekly suggestion.

It ``auto_install``s: installing both Pickleball Team and Alobo Connector brings
it in automatically; it stays absent (and both base modules work standalone)
otherwise.
    """,
    'author': 'Khaid',
    'depends': ['pickleball-team', 'alobo_connector'],
    'data': [
        'security/ir.model.access.csv',
        'data/cron_data.xml',
        'data/bot_command_data.xml',
        'wizard/views/court_search_wizard_views.xml',
        'wizard/views/court_search_result_views.xml',
        'wizard/views/court_schedule_wizard_views.xml',
        'views/pickleball_court_views.xml',
        'views/pickleball_session_views.xml',
    ],
    'installable': True,
    'auto_install': True,
    'application': False,
    'license': 'LGPL-3',
}
