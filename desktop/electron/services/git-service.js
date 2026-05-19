const { simpleGit } = require('simple-git')

function registerGitHandlers(ipcMain) {
  ipcMain.handle('git:status', async (_, repoPath) => {
    const git = simpleGit(repoPath)
    const status = await git.status()
    return {
      branch: status.current || 'unknown',
      staged: status.staged,
      unstaged: [...status.modified, ...status.deleted],
      untracked: status.not_added,
      ahead: status.ahead,
      behind: status.behind,
    }
  })

  ipcMain.handle('git:log', async (_, repoPath, count = 20) => {
    const git = simpleGit(repoPath)
    const log = await git.log(['-' + count])
    return log.all.map((c) => ({
      hash: c.hash,
      author: c.author_name,
      date: c.date,
      message: c.message,
    }))
  })

  ipcMain.handle('git:diff', async (_, repoPath, { staged, file } = {}) => {
    const git = simpleGit(repoPath)
    const args = []
    if (staged) args.push('--staged')
    if (file) args.push('--', file)
    return git.diff(args)
  })

  ipcMain.handle('git:branches', async (_, repoPath) => {
    const git = simpleGit(repoPath)
    const branches = await git.branch()
    return branches.all.map((name) => ({
      name,
      active: name === branches.current,
    }))
  })

  ipcMain.handle('git:commit', async (_, repoPath, { message, files } = {}) => {
    const git = simpleGit(repoPath)
    if (files && files.length > 0) {
      await git.add(files)
    } else {
      await git.add('-A')
    }
    await git.commit(message)
    return true
  })

  ipcMain.handle('git:checkout', async (_, repoPath, { branch, create } = {}) => {
    const git = simpleGit(repoPath)
    if (create) {
      await git.checkoutLocalBranch(branch)
    } else {
      await git.checkout(branch)
    }
    return true
  })

  ipcMain.handle('git:fetch', async (_, repoPath) => {
    const git = simpleGit(repoPath)
    await git.fetch()
    return true
  })

  ipcMain.handle('git:pull', async (_, repoPath) => {
    const git = simpleGit(repoPath)
    await git.pull()
    return true
  })

  ipcMain.handle('git:push', async (_, repoPath) => {
    const git = simpleGit(repoPath)
    await git.push()
    return true
  })

  ipcMain.handle('git:init', async (_, repoPath) => {
    const git = simpleGit(repoPath)
    await git.init()
    return true
  })

  ipcMain.handle('git:isRepo', async (_, repoPath) => {
    const git = simpleGit(repoPath)
    return git.checkIsRepo()
  })
}

module.exports = { registerGitHandlers }
