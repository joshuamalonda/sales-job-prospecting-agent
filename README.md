Problem:

Landly V1 brings together SDR & BDR (Sales Development Representative & Business Development Representative) job roles throughout the UK using APIs all into one place, but all the companies that get pulled in have to pass the filter of including SaaS/Technology/tech in the title or anywhere in the job description allowing users to filter for location(cities), when the job got posted(today, yesterday, last 7 days, last 2 weeks, last month), filter for keys words (included in the job description or title) so I can filter for any words I choose. I also want the jobs to be refreshed daily with the jobs that have just been added to be added to the top but at first it will pull in all job in the UK that have been posted in the last month. I have purposely left out other filters like, salary, company size(headcount), company stage (pre-seed, seed, series A, series B etc), industry(martech, fintech, proptech etc), also in the future I want a daily email with all the new jobs added with the last 24 hours.

Then for each company I want the app to allow me with a click of a button or even better if it pulls is in through API Apollo so I can get the right decision makers, I just want it to attach the company on apollo so I can go in and find the decison makers myself but in the future I want it with an API to automatically pull in the hiring manager, other Sdrs in the team, talent acquisition person, and VP of sales.

Then for each job post I want to be able to click it and press add to list and from there I want to press a button and it gives me a brief on what they sell, who they sell to and what they do. In the future I want to add recent news(their website blogs, headline company news, recent fundraise) to be pulled in aswell.

From this info I want it to then generate me a cold call, email, and message script for that company, and when I do add my CV I want it to get context from my CV and add that to the scripts aswell.

In the future I want it to generate a sales plan aswell for each company but more on that later.

Data sources: Reed.co.uk API(Free developer access using HTTP basic authentication, Adzuna UK API (Free for developers via registration (App ID + Key)), Greenhouse & Lever Public ATS (100% free and open by calling ⁠[https://boards-api.greenhouse.io/v1/boards/](https://boards-api.greenhouse.io/v1/boards/){company_token}/jobs⁠ or ⁠[https://api.lever.co/v0/postings/](https://api.lever.co/v0/postings/){company_name}⁠)


I will identify jobs posts that are the same by the company being the same (company name) and same exact job title

