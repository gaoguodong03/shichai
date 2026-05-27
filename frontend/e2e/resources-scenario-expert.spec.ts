import { expect, test } from '@playwright/test'
import { bootLoggedInApp } from './fixtures/mockApi'

test.describe('验收 3/6：资源中心场景与专家', () => {
  test('用户可以查看并保存场景配置', async ({ page }) => {
    await bootLoggedInApp(page)

    await page.getByRole('button', { name: '资源中心' }).click()
    await page.getByRole('button', { name: '场景', exact: true }).click()
    await expect(page.getByRole('heading', { name: '配置场景' })).toBeVisible()
    await expect(page.getByPlaceholder('请输入场景名称')).toHaveValue('问答验收场景')
    await expect(page.getByText('场景主持人')).toBeVisible()
    await expect(page.getByText('协作专家')).toBeVisible()

    await page.getByPlaceholder('请输入场景描述').fill('通过 UI 自动化保存的场景说明')
    await page.getByRole('button', { name: '保存' }).click()
    await expect(page.getByText('问答验收场景')).toBeVisible()
  })

  test('创建场景草稿未保存前不出现在场景列表', async ({ page }) => {
    await bootLoggedInApp(page, '/resources/scenario')

    const sidebar = page.getByRole('complementary')
    await page.getByRole('button', { name: '创建场景' }).click()
    await page.getByRole('button', { name: '创建场景' }).click()
    await page.getByRole('button', { name: '创建场景' }).click()

    await expect(page.getByRole('heading', { name: '创建场景' })).toBeVisible()
    await expect(sidebar.getByText('0 位专家', { exact: true })).toHaveCount(0)
  })

  test('用户可以创建专家并保存专家配置', async ({ page }) => {
    await bootLoggedInApp(page, '/resources/agent')

    await expect(page).toHaveURL(/\/resources\/agent$/)
    await expect(page.getByRole('complementary').getByText('问答专家').first()).toBeVisible()

    await page.getByRole('button', { name: '创建专家' }).click()
    await expect(page.getByRole('heading', { name: '创建专家' })).toBeVisible()
    await page.getByPlaceholder('请输入专家名称').fill('自动化专家')
    await page.getByPlaceholder('请输入专家描述').fill('负责验收真实用户点击路径')
    await page.getByRole('button', { name: '保存' }).click()

    await expect(page.getByRole('complementary').getByText('自动化专家').first()).toBeVisible()
  })

  test('专家详情页直接展示访问方式，不再使用分享按钮', async ({ page }) => {
    await bootLoggedInApp(page, '/resources/agent')

    await expect(page.getByRole('heading', { name: '配置专家' })).toBeVisible()
    await expect(page.getByRole('button', { name: '分享', exact: true })).toHaveCount(0)
    await expect(page.getByText('访问方式', { exact: true })).toBeVisible()
    await expect(page.getByRole('link', { name: /\/share\/run\?id=share-expert/ })).toBeVisible()
    await expect.poll(async () =>
      page.evaluate(() => {
        const form = document.querySelector('form')
        const access = Array.from(form?.querySelectorAll('div') || []).find((el) => el.textContent?.trim() === '访问方式')
        const save = Array.from(form?.querySelectorAll('button') || []).find((el) => el.textContent?.trim() === '保存')
        return Boolean(access && save && (access.compareDocumentPosition(save) & Node.DOCUMENT_POSITION_FOLLOWING))
      }),
    ).toBe(true)
  })
})
