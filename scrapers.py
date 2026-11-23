#!/usr/bin/env python3
"""Archive trips and convert archives and reminders to Pelican articles."""

import argparse
import os


def main():
    """Parse the selected command and dispatch it to its implementation."""
    parser = argparse.ArgumentParser(prog="scrapers", description=__doc__)
    commands = parser.add_subparsers(dest="command")

    findpenguins = commands.add_parser("findpenguins", help="Scrape FindPenguins profiles to adventures archive")
    findpenguins.add_argument("profiles", help="JSON file mapping profile names to {id, username, password}")
    findpenguins.add_argument("--output", default="output", help="Archive folder for XML, GPX and media (default: output)")
    findpenguins.add_argument("-t", "--trip", help="Trip slug to scrape only (default: all trips)")
    findpenguins.add_argument("--force", action="store_true", help="Clear the output folder before scraping (only the --trip trip when given)")
    findpenguins.add_argument("--skip", action="store_true", help="Use saved HTML snapshots without navigating; disables --force")

    polarsteps = commands.add_parser("polarsteps", help="Archive a Polarsteps profile using its API")
    polarsteps.add_argument("profiles", help="JSON file mapping profile names to {id, username, password}")
    polarsteps.add_argument("--output", default="output", help="Archive folder (default: output)")
    polarsteps.add_argument("-t", "--trip", help="Archive only this trip slug")
    polarsteps.add_argument("--force", action="store_true", help="Clear the output folder before scraping (only the --trip trip when given)")
    polarsteps.add_argument("--skip", action="store_true", help="Use saved API snapshots and existing media without logging in; disables --force")

    combined = commands.add_parser("aventures", help="Archive both services and generate Pelican articles")
    combined.add_argument("profiles", help="Shared profiles JSON file")
    combined.add_argument("--output", default="output", help="Parent archive folder (default: output)")
    combined.add_argument("--content", default="../website/content/articles", help="Parent Pelican articles folder")
    combined.add_argument("--force", action="store_true", help="Clear each service archive before scraping")
    combined.add_argument("--skip", action="store_true", help="Use saved snapshots for both services; disables --force")

    aventures = commands.add_parser("aventures2rst", help="Convert adventures archive to Pelican articles")
    aventures.add_argument("--output", default="output", help="Adventures archive directory")
    aventures.add_argument("--content", default="../website/content/articles/findpenguins", help="Pelican articles directory")
    aventures.add_argument("-t", "--trip", help="Only convert this trip slug")
    aventures.add_argument("--category", default="findpenguins", help="Pelican trip category and first service tag")

    reminder = commands.add_parser("reminder", help="Prepare an Apple Reminders export")
    reminder.add_argument("--output", required=True, help="Output directory")
    reminder.add_argument("--list", required=True, dest="list_name", help="Reminders list name")
    reminder.add_argument("--all", action="store_true", help="Include completed reminders")
    reminder.add_argument("--force", action="store_true", help="Delete the output directory first")

    reminders = commands.add_parser("reminders2rst", help="Convert exported reminders to Pelican articles")
    reminders.add_argument("--output", required=True, help="Reminder export directory")
    reminders.add_argument("--content", default="../website/content/articles/reminders", help="Pelican articles directory")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
    elif args.command == "findpenguins":
        from findpenguins import scrapper

        scrapper(args.profiles, args.output, args.trip, args.force, args.skip)
    elif args.command == "polarsteps":
        from polarsteps import scrape_profiles

        scrape_profiles(args.profiles, args.output, args.trip, force=args.force, skip=args.skip)
    elif args.command == "aventures":
        from findpenguins import scrapper
        from polarsteps import scrape_profiles
        from aventures2rst import convert as convert_aventures

        findpenguins_output = os.path.join(args.output, "findpenguins")
        polarsteps_output = os.path.join(args.output, "polarsteps")
        scrapper(args.profiles, findpenguins_output, None, args.force, args.skip)
        scrape_profiles(args.profiles, polarsteps_output, None, force=args.force, skip=args.skip)
        convert_aventures(findpenguins_output, os.path.join(args.content, "findpenguins"), None, "findpenguins")
        convert_aventures(polarsteps_output, os.path.join(args.content, "polarsteps"), None, "polarsteps")
    elif args.command == "aventures2rst":
        from aventures2rst import convert as convert_aventures

        convert_aventures(args.output, args.content, args.trip, args.category)
    elif args.command == "reminder":
        from reminder import export_reminders

        export_reminders(args.output, args.list_name, args.all, args.force)
    else:
        from reminders2rst import convert as convert_reminders

        convert_reminders(args.output, args.content)


if __name__ == "__main__":
    main()
